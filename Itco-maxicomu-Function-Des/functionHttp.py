import uuid
import os
import re
import io
import re
import pickle
import logging
import requests
import faiss
import tempfile
import pandas as pd
from datetime import datetime, timedelta, timezone
from langchain.vectorstores.faiss import FAISS
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain.chat_models import AzureChatOpenAI
from langchain_openai import AzureOpenAIEmbeddings
from utils.azure_clients import get_cosmos_container, get_blob_container, get_secrets
from utils.prompt import built_prompt


# Variables de entorno
# Definir tiempo máximo de conversación activa (24 horas)
time_hours = int(os.environ.get("time_hours", 24))
secret_openai_api_key = get_secrets("openai-api-key")
azure_endpoint = os.environ["AZURE_ENDPOINT"]
api_version = os.environ["openai_api_version"]


def download_greeting():  
    """Descarga el saludo y despedida de un archivo de texto ubicado en Storage Account."""
    try: 
        # Obtener una referencia al contenedor
        blob_container = get_blob_container("storage_container_basecono")
        blob_client = blob_container.get_blob_client("plano/SaludoDespedida.txt")
        
        # Descargar el contenido del archivo        
        blob_data = blob_client.download_blob()
        file_content = blob_data.readall().decode("utf-8")
        
        try:
            pattern = r"(?m)^(\w+):\s*([\s\S]+?)(?=\n\w+:|\Z)"
            matches = re.findall(pattern, file_content)
            sections = {key: value.strip() for key, value in matches}        
            logging.info("Secciones extraídas correctamente.")
        except Exception as regex_err:
            logging.error(f"Error en regex: {str(regex_err)}")
            matches = []
        
        greeting = sections.get("Saludo", "No se encontró Saludo")
        closing = sections.get("Cierre", "No se encontró Cierre") 
        feedback = sections.get("Feedback", "No se encontró Feedback") 
        feedback_comment = sections.get("FeedbackComment", "No se encontró comentario de Feedback") 
        thanks = sections.get("Gracias", "No se encontró Gracias")
        session_end = sections.get("Despedida", "No se encontró Despedida")
        infocorporativalabel = sections.get("InfoCorporativaLabel", "No se encontró etiqueta de información corporativa")
        infonocorporativalabel = sections.get("InfoNoCorporativaLabel", "No se encontró etiqueta de información no corporativa")
        infonocorporativa = sections.get("InfoNoCorporativa", "No se encontró Mensaje de información no corporativa")
        infoexterna = sections.get("InfoExterna", "No se encontró Mensaje de información externa")        
        
        return greeting, closing, feedback, feedback_comment, thanks, session_end, infocorporativalabel, infonocorporativalabel, infonocorporativa, infoexterna
    
    except Exception as e:
        logging.error(f"ERROR - getting greetings: {e}")
        raise


def download_vectorialdb():
    """Descarga el contexto de la BD vectorial."""
    try:
        
        # Cliente de Blob      
        blob_container = get_blob_container("storage_container_vectordb")

        # Descargar y leer faiss index
        data = blob_container.get_blob_client("index.faiss").download_blob().readall()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        index = faiss.read_index(path)

        # Descargar y deserializar pickle
        pkl = blob_container.get_blob_client("index.pkl").download_blob().readall()
        docstore, index_to_id = pickle.loads(pkl)
        
        # Embeddings con Azure        
        base_embeddings = AzureOpenAIEmbeddings(
            deployment=os.getenv("embedding_model_name"),
            azure_endpoint=azure_endpoint,
            api_key=secret_openai_api_key,
            api_version=api_version,
            chunk_size=1000
        )

        # Reconstruir vector store
        vs = FAISS(
            index=index,
            docstore=docstore,
            index_to_docstore_id=index_to_id,
            embedding_function=base_embeddings
        )
        logging.info("Vector store cargado correctamente")
        return vs

    except Exception as e:
        logging.error("ERROR al cargar base vectorial", exc_info=True)
        raise


def get_conversation(container, userId):
    """Obtiene las conversaciones almacenadas en la BD para cada usuario."""
    try:        
        # Ordenar por createdAt DESC y tomar el primero
        query = "SELECT * FROM c WHERE c.userId = @userId ORDER BY c.createdAt DESC OFFSET 0 LIMIT 1"
        
        # Ejecutar la consulta con parámetros
        existing_conversations = list(
            container.query_items(
                query=query,
                parameters=[{"name": "@userId", "value": userId}],
                enable_cross_partition_query=True
            )
        )        
        return existing_conversations[0] if existing_conversations else None    
    except Exception as e:
        logging.error(f'ERROR - getting conversation in database: {e}')
        raise        


def save_conversation(container, new_conversation_data):
    """Guarda la conversación en la Base de Datos."""
    try:       
        container.upsert_item(new_conversation_data)        
    except Exception as e:
        logging.error(f'ERROR - getting conversation in database: {e}')
        raise


def validate_policy(conversation_history):
    """Valida si la política de tratamiento de datos personales fue enviada y aceptada o negada."""
    try:
        show_policy = False
        accepted_policy = False
        
        for msg in conversation_history:
            if msg["role"] == "assistant" and msg.get("typeMessage") == "politica":
                show_policy = True  # Se mostró la política, ahora esperamos respuesta    
            elif show_policy and msg["role"] == "user":
                if msg["content"].strip() in ["accept"]:
                    accepted_policy = True
                elif msg["content"].strip() in ["reject"]:
                    accepted_policy = False  # Si en algún momento la negó, no aceptamos
                break  # Salimos del bucle después de la respuesta del usuario
        return not accepted_policy  # Devuelve 'False' si la política fue aceptada
    
    except Exception as e:
        logging.error(f"ERROR - validating policy: {e}")
        raise


def create_embeddings_with_openai(text_content):
    """Instancia embeddings desde AzureOpenaAIEmbeddings."""
    try:
        embeddings = AzureOpenAIEmbeddings(
                azure_deployment="text-embedding-ada")
        return embeddings.embed_query(text_content)
    except Exception as e:
        logging.error(f"ERROR - creating embeddings: {e}")
        raise


def extract_categories(docs, na):
    """Extrae las categorías de los documentos."""
    try:
        categories = []
        for doc in docs:
            match = re.search(r'CATEGORIA\s*:\s*(.*?)\.', doc.page_content, re.IGNORECASE)
            if match:
                categories.append(match.group(1).strip())
            else:
                categories.append("Categoría no encontrada")
                
        categories = drop_duplicates(categories, na)
        return categories
    except Exception as e:
        logging.error(f"ERROR - extracting categories: {e}")
        raise


def drop_duplicates (lista: list, na):
    """Borra duplicados en las listas de Categorías y Fuentes."""
    try:
        if lista:
                lista = list(set(lista))  # eliminar duplicados
        else:
            lista = [na]
        return lista
    except Exception as e:
        logging.error(f"ERROR - dropping duplicates: {e}")
        raise


def process_webhook_pricing(value):
    """Extrae la información facturable de la conversación desde el webhook."""
    try:
        pricing = value.get("pricing", {})
        if pricing:
            return {
                "billable": pricing.get("billable", True),
                "category": pricing.get("category", "unknown"),
                "pricing_model": pricing.get("pricing_model", "CBP")
            }
    except Exception as e:
        logging.warning(f"No se pudo procesar el pricing: {e}")
    return {"billable": False, "category": "service", "pricing_model": "N/A"}


def whatsapp_pricing_usd():
    """Obtiene la información del costo de la conversación para hacer el cálculo."""
    try:
        # Obtener una referencia al contenedor
        blob_container = get_blob_container("storage_container_basecono")
        blob_client = blob_container.get_blob_client("comunicados/costos.xlsx")
        
        # Descargar el contenido del archivo        
        blob_data = blob_client.download_blob()
        
        # Cargar el contenido del blob en un DataFrame de pandas
        excel_bytes = io.BytesIO(blob_data.readall())
        df = pd.read_excel(excel_bytes) 
        
        return df
    except Exception as e:
        logging.error(f'ERROR - getting whatsapp pricing: {e}')
        raise


def calculate_pricing(user_id, pricing_category: str):
    """Calcula el costo de la conversación."""
    try:
        price = 0
        
        df = whatsapp_pricing_usd()
        
        if user_id.startswith("57"):
            country = "CO"
        else:
            country = "UNKNOWN"        
        
        # Filtrar filas donde encuentre el país
        df_filtered = df[
            (df['PAIS'].astype(str).str.upper() == country) & 
            (df['CATEGORIA'].astype(str).str.upper() == pricing_category.upper())
            ]
        
        if not df_filtered.empty:
            price = df_filtered['PRECIOUSD'].iloc[0]            
        else:
            logging.info("No se encontró un precio para esa combinación.")
            
        return price
    except Exception as e:
        logging.error(f'ERROR - calculating price: {e}')
        raise


def build_openai_model():
    """Construye la instancia del modelo OpenAi."""
    try:
        return AzureChatOpenAI(
            temperature=0.0,
            deployment_name=os.environ["AZURE_DEPLOYMENT_MODEL_NAME"],
            api_key=secret_openai_api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version
        )
    except Exception as e:
        logging.error(f"ERROR - building openai model: {e}")
        raise


def preprocess_message(message, conversation_history, closing):
    """Estadariza ciertas expresiones que se pueden encontrar en el mensaje recibido."""
    try:
        msg = message.strip().upper()
        
        close_message = has_previous_closing_response(conversation_history, closing)        
        
        if "SERVIDUMBRE" in msg:
            message = (
                        "Estoy haciendo una consulta legal sobre una servidumbre eléctrica, servidumbre de transmisión de energía o servidumbre de transmisión de energía y telecomunicaciones. "
                        "Por favor, responde en ese contexto. " + message
                    )
        elif msg in {"SI", "SÍ", "ACEPTO", "CLARO", "DE ACUERDO"} and close_message:
            message = "SI"
        elif msg in {"SI", "SÍ", "ACEPTO", "CLARO", "DE ACUERDO"}:
            message = "accept"
        elif msg == "NO" and close_message:
            message = "NO"
        elif msg == "NO":
            message = "reject"        
        elif msg.strip() == "👍":
            message = "1"
        elif msg.strip() == "👎":
            message = "0"
        
        return message
    except Exception as e:
        logging.error(f"ERROR - processing message: {e}")
        raise


def initialize_conversation(now, user_id, user_name):
    """Inicializa una nueva conversación."""
    try:
        return {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "userName": user_name,
            "createdAt": now,
            "updatedAt": datetime(1900, 1, 1),
            "messages": [],
            "sessionStatus": "opened"
        }
    except Exception as e:
        logging.error(f"ERROR - initializing conversation: {e}")
        raise


def should_close_conversation(conversation, now, time_hours):
    """Determina si debe cerrarse una conversación existente."""
    try:
        created_at = datetime.fromisoformat(conversation["createdAt"])
        expired = (now - created_at) >= timedelta(hours=time_hours)
        manually_closed = conversation["sessionStatus"] == "closed"
        return expired or manually_closed
    except Exception as e:
        logging.error(f"ERROR - closing conversation: {e}")
        raise


def already_processed(conversation_history, message_id):
    """Determina si el mensaje ya fue procesado."""
    try:
        return any(msg.get("messageId") == message_id and msg["role"] == "assistant" for msg in conversation_history)
    except Exception as e:
        logging.error(f"ERROR - validating existing conversation: {e}")
        raise


def add_message(history, role, content, message_id, now, msg_type, fuente, categories):
    """Adiciona un mensaje al historial."""
    try:
        history.append({
            "role": role,
            "content": content,
            "date": now.isoformat(),
            "messageId": message_id,
            "typeMessage": msg_type,
            "fuente": fuente,
            "categories": categories
        })
    except Exception as e:
        logging.error(f"ERROR - adding message: {e}")
        raise


def build_prompt_and_messages(history, message, na, prompt):
    """Construye el mensaje a partir del prompt."""
    try:
        vector_store = download_vectorialdb()
        docs = vector_store.similarity_search(message, k=3)
        contexto = "\n".join([doc.page_content for doc in docs])    
        system_message = SystemMessage(content=f"{prompt}\n\nContexto relevante:\n{contexto}")
        messages = [system_message]
        
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        
        messages.append(HumanMessage(content=message))
        
        categories = extract_categories(docs, na)
        
        return messages, categories
    except Exception as e:
        logging.error(f"ERROR - building prompt: {e}")
        raise


def has_previous_closing_response(history, closing):
    """Devuelve True si ya existe un mensaje de cierre previo del asistente."""
    try:
        for msg in history:
            if msg["role"] == "assistant" and closing in msg.get("content", ""):
                return True
        return False
    except Exception as e:
        logging.error(f"ERROR - consulting previous closing: {e}")
        raise


def has_previous_feedback_response(history, feedback_comment):
    """Devuelve True si el asistente ya ha solicitado el comentario del feedback."""
    try:
        for msg in history:
            if msg["role"] == "assistant" and feedback_comment in msg.get("content", ""):
                return True
        return False
    except Exception as e:
        logging.error(f"ERROR - consulting previous feedback: {e}")
        raise


def openai_request(value):
    """Procesa el mensaje, obtiene respuesta de OpenAI y almacena la conversación en CosmosDB."""
    try:      
        # Datos principales
        value_messages = value.get("messages", [{}])[0]
        message = value_messages["text"]["body"]
        message_id = value_messages["id"]
        user_id = value_messages["from"]
        user_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Usuario")
        na = "No Aplica"
        categories = na
        fuente = na    
        send_greeting, send_feedback, send_session_end, send_comment, send_thanks = False, False, False, False, False
        session_status = "opened"
        now = datetime.now(timezone.utc)
        
        container = get_cosmos_container()

        conversation = get_conversation(container, user_id)

        if conversation:
            conversation_id = conversation["id"]
            conversation_history = conversation["messages"]
            createdAt = datetime.fromisoformat(conversation["createdAt"])
            updatedAt = now
            
            if already_processed(conversation_history, message_id):
                logging.info(f"Mensaje con ID {message_id} ya fue procesado.")
                return None
            
            if should_close_conversation(conversation, now, time_hours):
                logging.info("Conversación cerrada o expirada. Se crea una nueva.")
                conversation["sessionStatus"] = "closed"
                save_conversation(container, conversation)
                conversation = initialize_conversation(now, user_id, user_name)
                conversation_id = conversation["id"]
                createdAt = now
                conversation_history = conversation["messages"] 
                send_greeting = True
            elif validate_policy(conversation_history):
                logging.info("Política no aceptada")
                send_greeting = True
        else:
            logging.info("No existe ninguna. Se crea una nueva.")
            conversation = initialize_conversation(now, user_id, user_name)
            conversation_id = conversation["id"]
            createdAt = now
            updatedAt = datetime(1900, 1, 1)
            conversation_history = conversation["messages"]
            send_greeting = True
            
        model = build_openai_model()  
        greeting, closing, feedback, feedback_comment, thanks, session_end, infocorporativalabel, infonocorporativalabel, infonocorporativa, infoexterna = download_greeting()        
        prompt = built_prompt (infocorporativalabel, infonocorporativalabel, infonocorporativa, infoexterna)
        
        # Mensajes del usuario
        message = preprocess_message(message, conversation_history, closing)
        
        feedback_message = has_previous_feedback_response(conversation_history, feedback_comment)
        
        if message == "accept":
            send_session_end, send_greeting = False, False
            msg_type = "politica"            
            role = "user"
        elif message == "reject":
            send_session_end, send_greeting = True, False
            msg_type = "politica"            
            role = "user"        
        else:
            if message == "NO":
                send_feedback = True
            elif message == "1" or message == "0":
                send_comment = True
            elif feedback_message:
                send_thanks = True
                send_session_end = True
            msg_type = "normal"            
            role = "user"
            logging.info("No está respondiendo política")        
            
        add_message(conversation_history, role, message, message_id, now, msg_type, fuente, categories)
        
        # Respuestas del sistema
        if send_greeting:
            logging.info("Está enviando saludo")
            system_message  = SystemMessage(content=f"Hola {user_name}, {greeting}")
            msg_type = "politica"            
            role = "assistant"
            assistant_response = system_message.content        
        elif send_feedback:
            logging.info("Está enviando feedback")
            system_message = SystemMessage(content=feedback)
            msg_type = "feedback"  
            role = "assistant"
            assistant_response = system_message.content
        elif send_comment:
            logging.info("Está enviando comentario feedback")
            system_message = SystemMessage(content=feedback_comment)
            msg_type = "feedback"  
            role = "assistant"
            assistant_response = system_message.content
        elif send_thanks:
            logging.info("Está enviando agradecimiento comentario feedback")
            combined_content = f"{thanks} \n {session_end}"
            system_message = SystemMessage(content=combined_content)
            session_status = "closed"
            msg_type = "normal"  
            role = "assistant"
            assistant_response = system_message.content
        elif send_session_end:
            logging.info("Está enviando despedida")
            system_message = SystemMessage(content=session_end)
            session_status = "closed"
            msg_type = "politica"  
            role = "assistant"
            assistant_response = system_message.content
        else:
            logging.info("Está enviando respuesta temática")
            messages, categories = build_prompt_and_messages(conversation_history, message, na, prompt)
            msg_type = "normal"
            role = "assistant"
            response = model.invoke(messages)
            assistant_response = response.content
            logging.info(f"assistant_response:{assistant_response}")
            if assistant_response == infoexterna:                
                combined_content = f"{assistant_response} \n {closing}"
                logging.info(f"combined_content Entro:{combined_content}")
                assistant_response = combined_content               
        
        # Extraer fuentes usando patrón [DOCUMENTO]
        fuente = re.findall(r"\[(.*?)\]", assistant_response)
        fuente = drop_duplicates(fuente, na)  # eliminar duplicados
        
        print(f"Valor de fuente: {fuente!r} (tipo: {type(fuente)})")
        
        if fuente != [na]:
            assistant_response = f"{assistant_response}\n\n{closing}"
        else:
            categories = na
        
        add_message(conversation_history, role, assistant_response, message_id, now, msg_type, fuente, categories)       
        
        # Cálculo de precio
        pricing_info = process_webhook_pricing(value)        
        price = calculate_pricing(user_id, pricing_info["category"])
        
        # Almacenamiento final        
        save_conversation(container, {
            "id": conversation_id,
            "userId": user_id,
            "userName": user_name,
            "createdAt": createdAt.isoformat(),
            "updatedAt": updatedAt.isoformat(),
            "messages": conversation_history,
            "sessionStatus": session_status,
            "whatsappBill": pricing_info["billable"],
            "whatsappCategory": pricing_info["category"],
            "whatsappPricingModel": pricing_info["pricing_model"],
            "whatsappCostUSD": price
        })
        
        return assistant_response 
        
    except Exception as e:
        logging.error(f"ERROR - processing OpenAI request: {e}")
        raise


def send_whatsapp_message(body, message):
    """Envía la respuesta a WhatsApp usando la API de Meta"""
    try:
        
        # whatsapp_token = get_secrets("whatsapp-token")
        whatsapp_token = "EAATVIxJamLkBO71kS8j1LubZAgLALX9FJk8iYZBkN5IzTfk0bTz2ec1D6r3D6ZBGhBT8JH7KNpos4k0PEiyCUETaD9iLbYyQeLgdHZBZAeT4kqVKdZAnbxYRGdP5UubOyf6kENjCgOjSaAsMzCNX9dUOYJYicL2Je87vL2WslreMRVEFUkyynfv64RZAuW4zX6kywZDZD"
        secret_whatsapp_token = whatsapp_token.strip()
        value = body["entry"][0]["changes"][0]["value"]
        phone_number_id = value["metadata"]["phone_number_id"]
        from_number = value["messages"][0]["from"]
        headers = {
            "Authorization": f"Bearer {secret_whatsapp_token}",
            "Content-Type": "application/json",
        }
        
        url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
        
        data = {
            "messaging_product": "whatsapp",
            "to": from_number,
            "type": "text",
            "text": {"body": message},
        }
        
        try:
            response = requests.post(url, json=data, headers=headers, verify=False)
            response.raise_for_status()
            json_response = response.json()
            
            # Verifica si el mensaje fue aceptado
            if (
                "messages" in json_response and
                json_response["messages"][0].get("message_status") == "accepted"
            ):
                logging.info("Mensaje aceptado, no se reintentará.")
            else:
                logging.warning(f"Respuesta inesperada: {json_response}")
        
        except requests.exceptions.HTTPError as http_err:
            status_code = getattr(http_err.response, "status_code", "N/A")
            content = getattr(http_err.response, "text", str(http_err))
            if status_code == 400 and "pair rate limit hit" in content:
                logging.warning("Rate limit alcanzado.")
            else:
                logging.error(f"HTTP error al enviar: {status_code} - {content}")
        
        except requests.exceptions.RequestException as req_err:
            logging.error(f"Error de red al enviar mensaje: {req_err}")
        
        except Exception as e:
            logging.exception("Error inesperado al enviar el mensaje a WhatsApp")
        
    except KeyError as ke:
        logging.error(f"Clave faltante en el cuerpo del mensaje: {ke}")
    except Exception as e:
        logging.exception("ERROR - al preparar datos para enviar mensaje de WhatsApp")
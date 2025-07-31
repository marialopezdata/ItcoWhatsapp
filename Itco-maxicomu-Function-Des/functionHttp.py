import os
import re
import re
import pickle
import logging
import requests
import faiss
import tempfile
from unidecode import unidecode
from typing import List
from datetime import datetime, timezone
from langchain.vectorstores.faiss import FAISS
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain.chat_models import AzureChatOpenAI
from langchain_openai import AzureOpenAIEmbeddings
import utils.azure_clients as azure_clients
from utils.prompt import built_prompt
import utils.utils as utils


# Variables de entorno
# Definir tiempo máximo de conversación activa (24 horas)
time_hours = int(os.environ.get("time_hours", 24))
secret_openai_api_key = azure_clients.get_secrets("openai-api-key")
azure_endpoint = os.environ["AZURE_ENDPOINT"]
api_version = os.environ["openai_api_version"]

# whatsapp_token = azure_clients.get_secrets("whatsapp-token")
whatsapp_token = "EAATVIxJamLkBPFx54bbLzSpHKqrZCRjZB34Pgp2eisG8jvUhJUxa3lZA0amWn7V1bEOnhgZCqhucWzBNZALUUYYz7cJ954MRCqMgNOGSvA7lDiY4szazL8Sh6LtGcFsqM6kxEazUsAJcpGNnqAwZBLZBZCkZC8PvnNbQDhX81f7N4AcfU1vuEIvJ1JUKVpOIcMCj7DQZDZD"
secret_whatsapp_token = whatsapp_token.strip()

# MAX_WA_TEXT = 1024  # límite de WhatsApp
# TEXT_CHUNK_SIZE = 1000  # usamos un poco menos por seguridad


def download_greeting():  
    """Descarga el saludo y despedida de un archivo de texto ubicado en Storage Account."""
    try: 
        # Obtener una referencia al contenedor
        blob_container = azure_clients.get_blob_container("storage_container_basecono")
        blob_client = blob_container.get_blob_client("plano/SaludoDespedida.txt")
        
        # Descargar el contenido del archivo        
        blob_data = blob_client.download_blob()
        file_content = blob_data.readall().decode("utf-8")
        
        try:
            pattern = r"(?m)^(\w+):\s*([\s\S]+?)(?=\n\w+:|\Z)"
            matches = re.findall(pattern, file_content)
            sections = {key: value.strip() for key, value in matches}    
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
        btnrechazo = sections.get("TextoBotonRechazo", "No se encontró Texto para el botón de rechazo")
        
        return greeting, closing, feedback, feedback_comment, thanks, session_end, infocorporativalabel, infonocorporativalabel, infonocorporativa, infoexterna, btnrechazo
    
    except Exception as e:
        logging.error(f"ERROR - getting greetings: {e}")
        raise


def download_vectorialdb():
    """Descarga el contexto de la BD vectorial."""
    try:
        
        # Cliente de Blob      
        blob_container = azure_clients.get_blob_container("storage_container_vectordb")

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


def update_conversation_pricing_from_status(status: dict):
    """Procesa un status de WhatsApp y actualiza el documento correspondiente con pricing en Cosmos DB."""
    try:
        now = datetime.now(timezone.utc)
        container = azure_clients.get_cosmos_container()
        message_id = status.get("id")

        # Obtener valores de pricing
        pricing_info = utils.process_webhook_pricing(status)
        category = pricing_info["category"]
        billable = pricing_info["billable"]
        pricing_model = pricing_info["pricing_model"]
        status_value = status.get("status")
        
        logging.info(f"Procesando status de mensaje: {message_id} con categoría: {category}")

        # Consultar conversación que contenga ese message_id
        query = f"""
        SELECT * FROM c
        WHERE EXISTS (
            SELECT VALUE m FROM m IN c.messages
            WHERE m.messageId = '{message_id}'
        )
        """
        items = list(container.query_items(query=query, enable_cross_partition_query=True))

        if not items:
            logging.warning(f"No se encontró conversación con messageId {message_id}")
            return

        doc = items[0]
        user_id = doc.get("userId", "")
        
        if not user_id:
            logging.warning(f"Documento sin userId, no se puede calcular precio")
            return

        cost_usd = utils.calculate_pricing(user_id, category) if billable else 0
        
        # Buscar mensaje y agregarle el pricing
        found = False
        for m in doc.get("messages", []):
            if m.get("messageId") == message_id:
                if "whatsappPricing" in m:
                    logging.info(f"[SKIP] Mensaje {message_id} ya tiene pricing, no se sobrescribe.")
                    return  # ya tiene precio, no lo modificamos

                # Si no existe, lo agregamos
                m["whatsappPricing"] = {
                    "billable": billable,
                    "category": category,
                    "pricing_model": pricing_model,
                    "cost_usd": cost_usd,
                    "status": status_value
                }
                found = True
                break

        if not found:
            logging.warning(f"No se encontró el mensaje {message_id} en los mensajes de la conversación.")
            return

        # Calcular el total acumulado de la conversación
        total_cost = utils.calculate_total_cost(doc)
        doc["totalCostUSD"] = total_cost
        doc["updatedAt"] = now.isoformat()

        # Guardar conversación actualizada
        container.upsert_item(doc)       
        
        logging.info(f"[OK] Guardado pricing para mensaje: {message_id} | ${cost_usd:.4f}")

    except Exception as e:
        logging.error(f"ERROR - procesando status webhook: {e}")


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


def extract_user_message(value):
    """
    Extrae el contenido textual del mensaje del usuario, manejando texto plano o botones interactivos.
    """
    try:
        message = value["messages"][0]
        msg_type = message["type"]
        
        if msg_type == "text":
            return message["text"]["body"]
        elif msg_type == "interactive":
            interaction = message["interactive"]
            if interaction["type"] == "button_reply":
                return interaction["button_reply"].get("id") 
            elif interaction["type"] == "list_reply":
                return interaction["list_reply"]["title"]
            else:
                return f"[Tipo interactivo desconocido: {interaction['type']}]"
        else:
            return f"[Mensaje tipo {msg_type} no manejado]"
    
    except Exception as e:
        logging.error(f"Error al extraer mensaje del usuario: {e}")
        return "[Error al leer mensaje]"


# def preprocess_message(message, conversation_history, closing):
def preprocess_message(message):
    """Estadariza ciertas expresiones que se pueden encontrar en el mensaje recibido."""
    try:
        msg = unidecode(message.strip().upper())
        if "SERVIDUMBRE" in msg:
            message = (
                        "Estoy haciendo una consulta legal sobre una servidumbre eléctrica, servidumbre de transmisión de energía o servidumbre de transmisión de energía y telecomunicaciones. "
                        "Por favor, responde en ese contexto. " + message
                    )
        
        return message
    except Exception as e:
        logging.error(f"ERROR - processing message: {e}")
        raise


def build_prompt_and_messages(history, message, na, prompt, infoexterna):
    """Construye el mensaje a partir del prompt."""
    try:
        vector_store = download_vectorialdb()
        docs = vector_store.similarity_search(message, k=3)
        
        if not docs:
                return {
                    "response": infoexterna,
                    "sources": ["No Aplica"],
                    "categories": ["No Aplica"],
                    "context_used": False
                }
        
        context = "\n".join([f"Documento {i+1}: {doc.page_content}" for i, doc in enumerate(docs)])
        system_message = SystemMessage(content=f"{prompt}\n\nContexto relevante:\n{context}")
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
        message = extract_user_message(value)
        message_id = value_messages["id"]
        user_id = value_messages["from"]
        user_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Usuario")
        na = ["No Aplica"]
        categories = na
        fuente = na    
        send_greeting, send_feedback, send_session_end, send_comment, send_thanks = False, False, False, False, False
        session_status = "opened"
        now = datetime.now(timezone.utc)
        response_type = "text"       
        
        container = azure_clients.get_cosmos_container()

        conversation = utils.get_conversation(container, user_id)

        if conversation:
            conversation_id = conversation["id"]
            conversation_history = conversation["messages"]
            createdAt = datetime.fromisoformat(conversation["createdAt"])
            updatedAt = now        
            
            if utils.already_processed(conversation_history, message_id):
                logging.info(f"Mensaje con ID {message_id} ya fue procesado.")
                return None
            
            if utils.should_close_conversation(conversation, time_hours):
                logging.info("Conversación cerrada o expirada. Se crea una nueva.")
                conversation["sessionStatus"] = "closed"
                utils.save_conversation(container, conversation)
                conversation = utils.initialize_conversation(user_id, user_name)
                conversation_id = conversation["id"]
                createdAt = now
                conversation_history = conversation["messages"] 
                send_greeting = True
            elif validate_policy(conversation_history):
                logging.info("Política no aceptada")
                send_greeting = True
        else:
            logging.info("No existe ninguna. Se crea una nueva.")
            conversation = utils.initialize_conversation(user_id, user_name)
            conversation_id = conversation["id"]
            createdAt = now
            updatedAt = datetime(1900, 1, 1)
            conversation_history = conversation["messages"]
            send_greeting = True
            
        model = build_openai_model()  
        greeting, closing, feedback, feedback_comment, thanks, session_end, infocorporativalabel, infonocorporativalabel, infonocorporativa, infoexterna, btnrechazo = download_greeting()        
        prompt = built_prompt (infocorporativalabel, infonocorporativalabel, infonocorporativa, infoexterna)
        
        # Mensajes del usuario
        logging.info(f"message:{message}")
        message = preprocess_message(message)
        
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
            if message == "terminar":
                send_feedback = True
            elif message == "1" or message == "0":
                send_comment = True
                msg_type = "feedback" 
            elif feedback_message:
                send_thanks = True
                send_session_end = True
                msg_type = "feedback_comment" 
            if "msg_type" not in locals():
                msg_type = "normal"           
            role = "user"
            logging.info("No está respondiendo política")        
            
        utils.add_message(conversation_history, role, message, message_id, msg_type, fuente, categories)
        
        # Respuestas del sistema
        if send_greeting:
            logging.info("Está enviando saludo")
            assistant_response = f"Hola {user_name}, {greeting} ✅ Acepto ❌ No acepto"            
            msg_type = "politica"            
            role = "assistant"
            response_type = "interactive"
            
            response_content = {
                "type": "button",
                "body": {
                    "text": f"Hola {user_name}, {greeting}"
                },
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "accept", "title": "✅ Acepto"}},
                        {"type": "reply", "reply": {"id": "reject", "title": "❌ No acepto"}}
                    ]
                }
            }   
        elif send_feedback:
            logging.info("Está enviando feedback")
            assistant_response = f"{feedback} 👍 Si 👎 No"
            msg_type = "feedback" 
            role = "assistant"
            response_type = "interactive"
            
            response_content = {
                "type": "button",
                "body": {
                    "text": f"{feedback}"
                },
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "1", "title": "👍 Si"}},
                        {"type": "reply", "reply": {"id": "0", "title": "👎 No"}}
                    ]
                }
            }           
        elif send_comment:
            logging.info("Está enviando comentario feedback")
            system_message = SystemMessage(content=feedback_comment)
            msg_type = "feedback_comment"  
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
            messages, categories = build_prompt_and_messages(conversation_history, message, na, prompt, infoexterna)
            msg_type = "normal"
            role = "assistant"
            response = model.invoke(messages)
            assistant_response = response.content
            if assistant_response == infoexterna:
                send_whatsapp_message_from_id(user_id, assistant_response)               
                # combined_content = f"{closing} \n {btnrechazo}"  
                assistant_response = f"{assistant_response} \n {closing} \n {btnrechazo}"    
                role = "assistant"
                response_type = "interactive"           
                response_content = {
                    "type": "button",
                    "body": {
                        "text": f"{closing}"
                    },
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "terminar", "title": btnrechazo}}
                        ]
                    }
                }     
        
        # Extraer fuentes usando patrón [DOCUMENTO]
        fuente = re.findall(r"\[(.*?)\]", assistant_response)
        fuente = drop_duplicates(fuente, na)  # eliminar duplicados
        
        if fuente != [na]:
            # combined_content = f"{assistant_response} \n {closing}"
            send_whatsapp_message_from_id(user_id, assistant_response)   
            assistant_response = f"{assistant_response} \n {closing} \n {btnrechazo}"    
            role = "assistant"
            response_type = "interactive"           
            response_content = {
                    "type": "button",
                    "body": {
                        "text": f"{closing}"
                    },
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "terminar", "title": btnrechazo}}
                        ]
                    }
                }  
        else:
            categories = na        
        
        utils.add_message(conversation_history, role, assistant_response, message_id, msg_type, fuente, categories)       
        
        # Cálculo de precio para el caso de los mensajes uno a uno 
        pricing_info = utils.process_webhook_pricing(value)        
        price = utils.calculate_pricing(user_id, pricing_info["category"])
        
        whatsapp_pricing = {
            "billable": pricing_info["billable"],
            "category": pricing_info["category"],
            "pricing_model": pricing_info["pricing_model"],
            "cost_usd": price,
            "status": "service"
            }
        
        # Agregar pricing al último mensaje del bot (assistant)
        for msg in reversed(conversation_history):
            if msg["role"] == "assistant" and msg.get("messageId") == message_id:
                msg["whatsappPricing"] = whatsapp_pricing
                break        
        
        # Almacenamiento final        
        utils.save_conversation(container, {
            "id": conversation_id,
            "userId": user_id,
            "userName": user_name,
            "createdAt": createdAt.isoformat(),
            "updatedAt": updatedAt.isoformat(),
            "messages": conversation_history,
            "sessionStatus": session_status
        })
        
        if response_type == "interactive":
            return {
                "type": "interactive",
                "content": response_content
            }
        else:
            return {
                "type": "text",
                "content": assistant_response
            }
        
    except Exception as e:
        logging.error(f"ERROR - processing OpenAI request: {e}")
        raise




def send_whatsapp_message(body, message, interactive=False):
    """Envía la respuesta a WhatsApp usando la API de Meta"""
    try:        
        value = body["entry"][0]["changes"][0]["value"]
        phone_number_id = value["metadata"]["phone_number_id"]
        from_number = value["messages"][0]["from"]
        headers = {
            "Authorization": f"Bearer {secret_whatsapp_token}",
            "Content-Type": "application/json",
        }
        
        logging.info(f"message:{message}")
        logging.info(f"longitud message:{len(message)}")
        
        url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
        
        # Determinar si se debe enviar un mensaje de texto o interactivo
        if interactive:
            data = {
                "messaging_product": "whatsapp",
                "to": from_number,
                "type": "interactive",
                "interactive": message  # Aquí se espera que `message` ya sea el dict con botones
            }
        else:
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
        
        except KeyError as ke:
            logging.error(f"Clave faltante en el cuerpo del mensaje: {ke}")
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
        return None
    
    
def send_whatsapp_message_from_id(user_id, text):
    try:
        logging.info("Se llamó a send_whatsapp_message_from_id")
        phone_number_id = os.environ["phone_number_id"]
        # whatsapp_token = azure_clients.get_secrets("whatsapp-token")
        whatsapp_token = "EAATVIxJamLkBPFx54bbLzSpHKqrZCRjZB34Pgp2eisG8jvUhJUxa3lZA0amWn7V1bEOnhgZCqhucWzBNZALUUYYz7cJ954MRCqMgNOGSvA7lDiY4szazL8Sh6LtGcFsqM6kxEazUsAJcpGNnqAwZBLZBZCkZC8PvnNbQDhX81f7N4AcfU1vuEIvJ1JUKVpOIcMCj7DQZDZD"
        secret_whatsapp_token = whatsapp_token.strip()
        headers = {
            "Authorization": f"Bearer {secret_whatsapp_token}",
            "Content-Type": "application/json",
        }
        
        logging.info(f"headers:{headers}")
        
        url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
        logging.info(f"url:{url}")
        
        payload = {
            "messaging_product": "whatsapp",
            "to": user_id,
            "type": "text",
            "text": {"body": text}
        }
        logging.info(f"payload:{payload}")
        logging.info(f"Enviando mensaje a: {user_id}")
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logging.info(f"Mensaje de cierre enviado a {user_id}: {response.status_code} - {response.text}")
        except requests.exceptions.HTTPError as http_err:
            logging.error(f"Error HTTP al enviar mensaje: {http_err} - {response.text}")
        except Exception as e:
            logging.error(f"Error general al enviar mensaje: {e}")
    except Exception as e:
        logging.error(f"Error al enviar mensaje por inactividad: {e}")
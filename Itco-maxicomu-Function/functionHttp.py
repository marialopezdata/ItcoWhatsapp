import uuid
import os
import re
import io
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
        
        # Expresiones regulares para extraer el saludo y la despedida
        greeting_match = re.search(r"Saludo:\s*(.*?)(?=\s*Despedida:|$)", file_content, re.DOTALL)
        closing_match = re.search(r"Despedida:\s*(.*)", file_content, re.DOTALL)
        
        # Saludo
        greeting = (
            greeting_match[1].strip()
            if greeting_match
            else "Saludo no encontrado"
        )
        
        # Despedida
        closing = (
            closing_match[1].strip()
            if closing_match
            else "Despedida no encontrada"
        )
        
        return greeting, closing
    
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
    show_policy = False
    accepted_policy = False
    
    for msg in conversation_history:
        if msg["role"] == "assistant" and msg.get("type_message") == "politica":
            show_policy = True  # Se mostró la política, ahora esperamos respuesta            
        elif show_policy and msg["role"] == "user":
            if msg["content"].strip().upper() in ["SI", "SÍ"]:
                accepted_policy = True
            elif msg["content"].strip().upper() in ["NO"]:
                accepted_policy = False  # Si en algún momento la negó, no aceptamos
            break  # Salimos del bucle después de la respuesta del usuario
    return not accepted_policy  # Devuelve 'False' si la política fue aceptada


def create_embeddings_with_openai(text_content):
    embeddings = AzureOpenAIEmbeddings(
            azure_deployment="text-embedding-ada")
    return embeddings.embed_query(text_content)


def extract_categories(docs):
    categories = []
    for doc in docs:
        match = re.search(r'CATEGORIA\s*:\s*(.*?)\.', doc.page_content, re.IGNORECASE)
        if match:
            categories.append(match.group(1).strip())
        else:
            categories.append("Categoría no encontrada")
            
    categories = drop_duplicates(categories)
    return categories


def drop_duplicates (lista: list):
    if lista:
            lista = list(set(lista))  # eliminar duplicados
    else:
        lista.append("Información no encontrada")
    return lista


def process_webhook_pricing(value):
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


def openai_request(value, **kwargs):
    """Procesa el mensaje, obtiene respuesta de OpenAI y almacena la conversación en CosmosDB."""
    try:
        
        container = get_cosmos_container()
        now = datetime.now(timezone.utc)
        send_greeting, send_closing = False, False
        session_status = "opened"
        value_messages = value.get("messages", [{}])[0]
        message = value_messages["text"]["body"]
        message_id = value_messages["id"]
        user_id = value_messages["from"]
        user_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Usuario")
        categories = "No Aplica"
        model = AzureChatOpenAI(
            temperature=0.0,
            deployment_name=os.environ["AZURE_DEPLOYMENT_MODEL_NAME"],
            api_key=secret_openai_api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version
        )

        # Agregar contexto si contiene "servidumbre"
        if "servidumbre" in message.lower():
            message = (
                "Estoy haciendo una consulta legal sobre una servidumbre eléctrica, servidumbre de transmisión de energía o servidumbre de transmisión de energía y telecomunicaciones. "
                "Por favor, responde en ese contexto. " + message
            )

        pricing_info = process_webhook_pricing(value)

        billable = pricing_info["billable"]
        pricing_category = pricing_info["category"]
        pricing_model = pricing_info["pricing_model"]
        
        price = calculate_pricing(user_id, pricing_category)
        
        
        conversation = get_conversation(container, user_id)

        if conversation:
            conversation_id = conversation["id"]
            conversation_history = conversation["messages"]
            createdAt = datetime.fromisoformat(conversation["createdAt"])
            updatedAt = now
            
            # Validar si ya se respondió este mensaje
            if any(msg.get("messageId") == message_id and msg["role"] == "assistant" for msg in conversation_history):
                logging.info(f"Mensaje con ID {message_id} ya fue procesado. No se generará una nueva respuesta.")
                return None  # O una cadena vacía

            if (now - createdAt) >= timedelta(hours=time_hours):
                logging.info("Se cerrará la conversación")
                conversation["session_status"] = "closed"
                save_conversation(container, conversation)
                conversation_id = str(uuid.uuid4())
                createdAt = now
                updatedAt = datetime(1900, 1, 1)
                conversation_history = []
                send_greeting = True
            elif conversation["session_status"] == 'closed':
                logging.info("Conversación Cerrada, se crea una nueva")
                conversation_id = str(uuid.uuid4())
                createdAt = now
                updatedAt = datetime(1900, 1, 1)
                conversation_history = []
                send_greeting = True
            elif validate_policy(conversation_history):  # Esta función debe revisar bien el historial
                send_greeting = True
                logging.info("Política no aceptada")
        else:
            conversation_id = str(uuid.uuid4())
            createdAt = now
            updatedAt = datetime(1900, 1, 1)
            conversation_history = []
            send_greeting = True

        greeting, closing = download_greeting()

        # Aceptación explícita de la política
        if message.strip().upper() in {"SI", "SÍ", "ACEPTO", "CLARO", "DE ACUERDO"}:
            send_greeting, send_closing = False, False
            conversation_history.append({
                "role": "user",
                "content": message,
                "date": now.isoformat(),
                "messageId": message_id,
                "type_message": "politica"  # Esto es clave
            })
        elif message.strip().upper() == "NO":
            send_closing, send_greeting = True, False
            conversation_history.append({
                "role": "user",
                "content": message,
                "date": now.isoformat(),
                "messageId": message_id,
                "type_message": "politica"  # También etiquetar el "NO"
            })

        # Almacenar mensaje original (normal)
        conversation_history.append({
            "role": "user",
            "content": message,
            "date": now.isoformat(),
            "messageId": message_id,
            "type_message": "normal"
        })

        if send_greeting:
            system_message = SystemMessage(content=f"Hola {user_name}, {greeting}")
            type_message = "politica"
        else:
            system_message, type_message = None, "normal"

        if send_closing:
            closing_message = SystemMessage(content=closing)
            session_status = "closed"
            conversation_history.append({
                "role": "assistant",
                "content": closing_message.content,
                "date": now.isoformat(),
                "messageId": message_id,
                "type_message": "closing"
            })
            save_conversation(container, {
                "id": conversation_id,
                "userId": user_id,
                "user_name": user_name,
                "createdAt": createdAt.isoformat(),
                "updatedAt": updatedAt.isoformat(),
                "messages": conversation_history,
                "session_status": session_status
            })
            return closing_message.content

        vector_store = download_vectorialdb()
        docs = vector_store.similarity_search(message, k=3)
        contexto = "\n".join([doc.page_content for doc in docs])
        
        prompt_detallado = """Eres un experto en derecho administrativo y urbanismo, especializado en gestión predial e infraestructura pública conforme a las normativas colombianas. Tu función principal es responder las 
        preguntas del usuario priorizando siempre el contenido documental proporcionado en el contexto. Si no encuentras información suficiente en los documentos, puedes complementar la respuesta con otras fuentes, 
        pero debes indicarlo explícitamente.

            INSTRUCCIONES ESTRICTAS:

                1. Analiza cuidadosamente la consulta del usuario y el contexto documental.
                
                2. Prioriza las respuestas basadas en el contenido del contexto:

                    * Si la respuesta está completa en el contexto, utiliza exclusivamente esa información y **añade la etiqueta [INFORMACIÓN CORPORATIVA] al final de la respuesta.**

                    * Si la pregunta está relacionada con los temas del contexto (gestión predial, normativas colombianas, derecho administrativo o urbanismo), **pero no hay suficiente información documental**, puedes complementar con conocimientos externos. En ese caso:
                        - Comienza la respuesta con esta frase exacta:  
                        `"Con la información corporativa que conozco, no puedo responder completamente tu pregunta 🙁. Pero he encontrado esta información No corporativa."`
                        - Añade **al final de la respuesta la etiqueta [INFORMACIÓN NO CORPORATIVA]**

                3.  Cada afirmación basada en los documentos debe citar su fuente al final de la respuesta, indicando:
                        - `Fuentes consultadas: [NOMBRE DEL DOCUMENTO]`
                        - Añade después la etiqueta correspondiente: `[INFORMACIÓN CORPORATIVA]` o `[INFORMACIÓN NO CORPORATIVA]` según sea el caso.
                
                4. Si hay contradicciones entre documentos, menciónalas explícitamente CITANDO AMBAS FUENTES.
                
                5. Si solo se encuentra información **parcial** en el contexto, debes aclararlo utilizando SIEMPRE la frase: 
                    "con la información corporativa que conozco, no puedo responder completamente tu pregunta 🙁. pero he encontrado esta información No corporativa"
                
                6. Usa un lenguaje técnico apropiado pero comprensible. No repitas frases innecesarias ni agregues conclusiones fuera del alcance documental.
                
                RESPUESTAS SEGÚN TIPO DE ENTRADA
                1. Si la entrada del usuario es una pregunta temática válida:

                    * Responde basándote preferentemente en el contexto.

                    * Si usas conocimientos externos, añade una nota:
                        "con la información corporativa que conozco, no puedo responder completamente tu pregunta 🙁. pero he encontrado esta información No corporativa"

                    * Incluye, si corresponde:

                        * Fuentes consultadas con formato correcto.

                        * Observaciones, si hay contradicción o falta de información.

                        * Limitaciones, si aplica.

                        * Cierra solo en este caso con: “¿Puedo ayudarte en algo más relacionado con este tema?”

                2. Si la entrada del usuario es un saludo, despedida o mensaje breve no temático (como "sí", "no", "gracias", etc.):

                    * Responde cordialmente según el caso.

                    * No incluyas el mensaje de limitación ni la frase de cortesía o la frase “¿Puedo ayudarte en algo más relacionado con este tema?”

                3. Si la pregunta está fuera del ámbito temático o no puede responderse ni con el contexto ni con conocimiento general:

                    * Responde exclusivamente con el mensaje:
                        "con la información corporativa que conozco, no puedo responder tu pregunta 🙁. También puedes probar preguntando de otra manera o consultando información adicional mediante nuestras líneas de atención o redes sociales"               
                

            IMPORTANTE: Nunca inventes, completes ni infieras información que no esté en el contexto o en conocimientos profesionales verificables. Cualquier dato externo debe diferenciarse claramente del contenido documental.
            """

        if not send_greeting:
            system_message = SystemMessage(content=f"{prompt_detallado}\n\nContexto relevante:\n{contexto}")

        messages = []
        if system_message:
            messages.append(system_message)

        for msg in conversation_history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))

        messages.append(HumanMessage(content=message))

        # Corrección del orden de mensajes y duplicidad
        response = model.invoke(messages)
        assistant_response = system_message.content if system_message else response.content
        if type_message == "normal":
            assistant_response = response.content
            
        # Extraer fuentes usando patrón [DOCUMENTO]
        fuentes = re.findall(r"\[(.*?)\]", assistant_response)
        fuentes = drop_duplicates(fuentes)  # eliminar duplicados
        
        if "INFORMACIÓN CORPORATIVA" in fuentes:
            categories = extract_categories(docs)        
        
        logging.info(f"Categorías encontradas en documentos vectoriales: {categories}")

        conversation_history.append({
            "role": "assistant",
            "content": assistant_response,
            "date": now.isoformat(),
            "messageId": message_id,
            "type_message": type_message,
            "fuente": fuentes,
            "categories": categories
        })

        save_conversation(container, {
            "id": conversation_id,
            "userId": user_id,
            "user_name": user_name,
            "createdAt": createdAt.isoformat(),
            "updatedAt": updatedAt.isoformat(),
            "messages": conversation_history,
            "session_status": session_status,
            "whatsapp_bill": billable,
            "whatsapp_category": pricing_category,
            "whatsapp_pricing_model": pricing_model,
            "whatsapp_cost_usd": price
        })

        return assistant_response
    except Exception as e:
        logging.error(f"ERROR - processing OpenAI request: {e}")
        raise



def send_whatsapp_message(body, message):
    """Envía la respuesta a WhatsApp usando la API de Meta"""
    try:
        whatsapp_token = get_secrets("whatsapp-token")
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
            logging.info(f"json_response api:{json_response}")
            
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
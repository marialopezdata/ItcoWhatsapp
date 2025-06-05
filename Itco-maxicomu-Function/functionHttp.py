import uuid
import os
import re
import pickle
import logging
import requests
import faiss
import tempfile
from datetime import datetime, timedelta, timezone
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient
from langchain.vectorstores.faiss import FAISS
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain.chat_models import AzureChatOpenAI
from langchain_openai import AzureOpenAIEmbeddings
from azure.identity import DefaultAzureCredential
from utils.azure_clients import get_cosmos_container, get_blob_container, get_credential
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient


# URL del Key Vault
key_vault_url = os.environ["key_vault_url"]

# Configuración de OpenAI
# os.environ["OPENAI_API_KEY"] = os.environ["openai_api_key"]
os.environ["OPENAI_API_TYPE"] = os.environ["openai_api_type"]
os.environ["OPENAI_API_VERSION"] = os.environ["openai_api_version"]
os.environ["AZURE_DEPLOYMENT_MODEL_NAME"] = os.environ["AZURE_DEPLOYMENT_MODEL_NAME"]
os.environ["AZURE_OPENAI_ENDPOINT"] = os.environ["AZURE_ENDPOINT"]

# Token de verificación para WhatsApp Business Account
whatsapp_token = os.environ["whatsapp_token"]

# Conexión a Cosmos DB
db_endpoint = os.environ["cosmos_endpoint"]
# db_key = os.environ["cosmos_key"]
db_name = os.environ["cosmos_db_name"]
db_container = os.environ["cosmos_container_name"]

credential = DefaultAzureCredential()
account_url = os.environ["storage_account_url"]
blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)

# Conexión a Azure Blob Storage
# container_name_baseCon = os.environ['storage_container_basecono']
# container_name_baseVec = os.environ['storage_container_vectordb']

# Definir tiempo máximo de conversación activa (24 horas)
TIMEOUT_HOURS = os.environ["time_hours"]


def get_secrets(secret_name):
    try:
        # Autenticación con la identidad administrada
        credential = get_credential()

        # Cliente para consultar secretos
        client = SecretClient(vault_url=key_vault_url, credential=credential)

        # Obtener un secreto
        # secret_name = "webhook-token"
        retrieved_secret = client.get_secret(secret_name)

        logging.info(f"Valor del secreto: {retrieved_secret.value}")
        
    except Exception as e:
        logging.error(f"ERROR - getting secret: {e}")
        raise


def download_greeting():  
    """Descarga el saludo y despedida de un archivo de texto ubicado en Storage Account."""
    try: 
        # blob_name = "plano/SaludoDespedida.txt"
        
        # Obtener una referencia al contenedor
        # container_client = blob_service_client.get_container_client(container_name_baseCon)
        blob_container = get_blob_container("storage_container_basecono")
        blob_client = blob_container.get_blob_client("plano/SaludoDespedida.txt")
        # Descargar el contenido del archivo
        # blob_client = container_client.get_blob_client(blob_name)
        
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
        secret_openai_api_key = get_secrets("openai-api-key")
        
        
        # Cliente de Blob      
        # client = blob_service_client.get_container_client(container_name_baseVec)
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
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            # api_key=os.getenv("OPENAI_API_KEY"),
            api_key=secret_openai_api_key,
            api_version=os.getenv("OPENAI_API_VERSION"),
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


def validar_politica(conversation_history):
    """Valida si la política de tratamiento de datos personales fue enviada y aceptada o negada."""
    politica_mostrada = False
    politica_aceptada = False
    
    for msg in conversation_history:
        if msg["role"] == "assistant" and msg.get("type_message") == "politica":
            politica_mostrada = True  # Se mostró la política, ahora esperamos respuesta            
        elif politica_mostrada and msg["role"] == "user":
            if msg["content"].strip().upper() in ["SI", "SÍ"]:
                politica_aceptada = True
            elif msg["content"].strip().upper() in ["NO"]:
                politica_aceptada = False  # Si en algún momento la negó, no aceptamos
            break  # Salimos del bucle después de la respuesta del usuario
    return not politica_aceptada  # Devuelve 'False' si la política fue aceptada


def create_embeddings_with_openai(text_content):
    embeddings = AzureOpenAIEmbeddings(
            azure_deployment="text-embedding-ada")
    return embeddings.embed_query(text_content)


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
        model = AzureChatOpenAI(temperature=0.0, deployment_name=os.environ["AZURE_DEPLOYMENT_MODEL_NAME"], **kwargs)

        # CAMBIO: Agregar contexto si contiene "servidumbre"
        if "servidumbre" in message.lower():
            message = (
                "Estoy haciendo una consulta legal sobre una servidumbre eléctrica, servidumbre de transmisión de energía o servidumbre de transmisión de energía y telecomunicaciones. "
                "Por favor, responde en ese contexto. " + message
            )

        conversation = get_conversation(container, user_id)

        if conversation:
            conversation_id = conversation["id"]
            conversation_history = conversation["messages"]
            createdAt = datetime.fromisoformat(conversation["createdAt"])
            updatedAt = now
            time_hours = int(TIMEOUT_HOURS)

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
            elif validar_politica(conversation_history):  # Esta función debe revisar bien el historial
                send_greeting = True
                logging.info("Política no aceptada")
        else:
            conversation_id = str(uuid.uuid4())
            createdAt = now
            updatedAt = datetime(1900, 1, 1)
            conversation_history = []
            send_greeting = True

        greeting, closing = download_greeting()

        # CAMBIO: Aceptación explícita de la política
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
        logging.info(f"contexto:{contexto}")

        if not send_greeting:
            system_message = SystemMessage(content=f"Contexto relevante:\n{contexto}")

        messages = []
        if system_message:
            messages.append(system_message)

        for msg in conversation_history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))

        messages.append(HumanMessage(content=message))

        # CAMBIO: Corrección del orden de mensajes y duplicidad
        response = model.invoke(messages)
        assistant_response = system_message.content if system_message else response.content
        if type_message == "normal":
            assistant_response = response.content

        conversation_history.append({
            "role": "assistant",
            "content": assistant_response,
            "date": now.isoformat(),
            "messageId": message_id,
            "type_message": type_message
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

        return assistant_response
    except Exception as e:
        logging.error(f"ERROR - processing OpenAI request: {e}")
        raise



def send_whatsapp_message(body, message):
    """Envía la respuesta a WhatsApp usando la API de Meta"""
    try:
        value = body["entry"][0]["changes"][0]["value"]
        phone_number_id = value["metadata"]["phone_number_id"]
        from_number = value["messages"][0]["from"]
        headers = {
            "Authorization": f"Bearer {whatsapp_token}",
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
                logging.info(f"Mensaje aceptado, no se reintentará.")
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
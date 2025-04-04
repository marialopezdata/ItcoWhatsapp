import uuid
import os
import io
import re
import logging
import requests
from datetime import datetime, timedelta, timezone
from azure.cosmos import CosmosClient, PartitionKey
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from azure.storage.blob import BlobServiceClient, ContentSettings
from langchain.chat_models import AzureChatOpenAI
from utils.utils import Text

# Configuración de OpenAI
os.environ["OPENAI_API_KEY"] = os.environ["KeyVaultGPT"]
os.environ["OPENAI_API_BASE"] = os.environ["OpenaiApiBase"]
os.environ["OPENAI_API_TYPE"] = os.environ["OpenaiApiType"]
os.environ["OPENAI_API_VERSION"] = os.environ["OpenaiApiVersion"]

# Token de verificación para WhatsApp Business Account
whatsapp_token = os.environ.get("WhatsappToken", "")

# Conexión a Cosmos DB
db_endpoint = os.environ["CosmosEndpoint"]
db_key = os.environ["CosmosKey"]
db_name = os.environ["CosmosDbName"]
db_container = os.environ["CosmosContainerName"]

# Conexión a Azure Blob Storage
storage_connection_string = os.environ["AzStgConnectionString"]
container_name = os.environ['AzStgContainerName']

# Definir tiempo máximo de conversación activa (24 horas)
TIMEOUT_HOURS = 1

# Función para descargar el archivo paramétrico mensaje saludo
def download_greeting():  
    """Descarga el saludo y despedida de un archivo de texto ubicado en Storage Account."""
    try: 
        blob_name = "plano/parametrizacion.txt"
        
        # Conexión a la cuenta de almacenamiento con la clave de acceso
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        
        # Obtener una referencia al contenedor
        container_client = blob_service_client.get_container_client(container_name)
        
        # Descargar el contenido del archivo
        blob_client = container_client.get_blob_client(blob_name)
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


def get_conversation(container, userId):
    try:        
        # Consulta corregida: Ordenamos por createdAt DESC y tomamos el primero
        query = "SELECT * FROM c WHERE c.userId = @userId ORDER BY c.createdAt DESC OFFSET 0 LIMIT 1"

        # Ejecutamos la consulta con parámetros
        existing_conversations = list(
            container.query_items(
                query=query,
                parameters=[{"name": "@userId", "value": userId}],
                enable_cross_partition_query=True
            )
        )

        logging.info(f"existing_conversations:{existing_conversations}")
        return existing_conversations[0] if existing_conversations else None
    
    except Exception as e:
        logging.error(f'ERROR - getting conversation in database: {e}')
        raise        
        
        
def save_conversation(container, new_conversation_data):
    try:       
        
        logging.info(f"new_conversation_data:{new_conversation_data}")
        
        container.upsert_item(new_conversation_data)
        
    except Exception as e:
        logging.error(f'ERROR - getting conversation in database: {e}')
        raise


# def verificar_politica(conversation_history):
#     """Verifica si se debe volver a solicitar la aceptación de la política."""
#     politica_enviada = False
#     politica_aceptada = False
    
#     for msg in conversation_history:
#         if msg["role"] == "user" and msg["content"].strip().upper() in ["SI", "SÍ"]:
#             politica_aceptada = True
#         if msg["role"] == "assistant" and msg.get("type_message") == "politica":
#             return not politica_aceptada  # Si ya aceptó, no la volvemos a pedir

#     return True  # Si nunca se envió la política, la pedimos


def validar_politica(conversation_history):
    logging.info(f"Historial de conversación: {conversation_history}")

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

    return not politica_aceptada  # Devuelve `False` si la política fue aceptada



def openai_request(value, **kwargs):
    """Procesa el mensaje, obtiene respuesta de OpenAI y almacena la conversación en CosmosDB."""
    try:
        client = CosmosClient(db_endpoint, db_key)
        database = client.get_database_client(db_name)
        container = database.get_container_client(db_container)

        now = datetime.now(timezone.utc)
        session_status = "opened"
        value_messages = value.get("messages", [{}])[0]
        message = value_messages["text"]["body"]
        message_id = value_messages["id"]
        user_id = value_messages["from"]
        user_name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Usuario")

        model = AzureChatOpenAI(temperature=0.0, deployment_name="pru-maxi-chat", **kwargs)

        conversation = get_conversation(container, user_id)

        send_greeting, send_closing = False, False

        if conversation:
            # conversation = existing_conversations[0]
            conversation_id = conversation["id"]
            conversation_history = conversation["messages"]
            createdAt = datetime.fromisoformat(conversation["createdAt"])
            updatedAt = now

            if (now - createdAt) >= timedelta(hours=TIMEOUT_HOURS):
                logging.info("Se cerrará la conversación")
                conversation["session_status"] = "closed"
                logging.info(f"Se cerrará la conversación: {conversation}")
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
            elif validar_politica(conversation_history):
                send_greeting = True
                logging.info("Política no aceptada")


                    
                    # else:
                    #     if (updatedAt - createdAt >= timedelta(hours=TIMEOUT_HOURS)):
                    #         send_greeting = True                    
                    #         session_status = "closed"
                    #         conversation_id = str(uuid.uuid4())
                    #         conversation_history.append({
                    #             "role": "assistant",
                    #             "content": "cierre automático 24 horas",
                    #             "date": now.isoformat(),
                    #             "messageId": message_id,
                    #             "type_message": "closing"
                    #         })

                    #         # Guardar conversación en la base de datos
                    #         new_conversation_data = {
                    #             "id": conversation_id,
                    #             "userId": user_id,
                    #             "user_name": user_name,
                    #             "createdAt": createdAt.isoformat(),
                    #             "updatedAt": updatedAt.isoformat(),
                    #             "messages": conversation_history,
                    #             "session_status": session_status
                    #         }
                    #         save_conversation(container, new_conversation_data)
                    #     elif verificar_politica(conversation_history):
                    #         send_greeting = True
                    #     else:
                    #         send_greeting = False
                    
                    # if (updatedAt - createdAt >= timedelta(hours=TIMEOUT_HOURS)):
                    #     send_greeting = True

        # else:
        #     conversation_id = str(uuid.uuid4())
        #     createdAt = now
        #     updatedAt = datetime(1900, 1, 1)
        #     conversation_history = []
        #     send_greeting = True

        greeting, closing = download_greeting()

        # Almacenar mensaje del usuario antes de cualquier acción
        conversation_history.append({
            "role": "user",
            "content": message,
            "date": now.isoformat(),
            "messageId": message_id,
            "type_message": "normal"
        })


        if message.upper() == "SI":
            send_greeting, send_closing = False, False
        elif message.upper() == "NO":
            send_closing, send_greeting = True, False


        if send_greeting:
            system_message = SystemMessage(content=f"Hola {user_name}, {greeting}")
            type_message = "politica"
        else:
            system_message, type_message = None, "normal"

        if send_closing:
            closing_message = SystemMessage(content=closing)
            session_status = "closed"
            # Agregar mensaje de cierre al historial de conversación
            conversation_history.append({
                "role": "assistant",
                "content": closing_message.content,
                "date": now.isoformat(),
                "messageId": message_id,  # Puede ser el mismo ID del usuario o generar uno nuevo
                "type_message": "closing"
            })

            # Guardar conversación en la base de datos
            new_conversation_data = {
                "id": conversation_id,
                "userId": user_id,
                "user_name": user_name,
                "createdAt": createdAt.isoformat(),
                "updatedAt": updatedAt.isoformat(),
                "messages": conversation_history,
                "session_status": session_status
            }
            logging.info(f"new_conversation_data:{new_conversation_data}")
            save_conversation(container, new_conversation_data)

            return closing_message.content

        # conversation_history.append({"role": "user", "content": message, "date": now.isoformat(), "messageId": message_id, "type_message": None})
        messages = [HumanMessage(content=msg["content"]) for msg in conversation_history]

        if system_message:
            messages.insert(0, system_message)

        response = model.invoke(messages)
        assistant_response = system_message.content if system_message else response.content

        if type_message == "normal":
            assistant_response = response.content

        conversation_history.append({"role": "assistant", "content": assistant_response, "date": now.isoformat(), "messageId": message_id, "type_message": type_message})

        new_conversation_data = {
            "id": conversation_id,
            "userId": user_id,
            "user_name": user_name,
            "createdAt": createdAt.isoformat(),
            "updatedAt": updatedAt.isoformat(),
            "messages": conversation_history,
            "session_status": session_status
        }

        save_conversation(container, new_conversation_data)
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
        # status_obj = value["statuses"][0]

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
        logging.info(f"json:{data}")
        logging.info(f"headers:{headers}")
        # logging.info(f"status_obj:{status_obj}")
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()

    except Exception as e:
        logging.error(f'ERROR - sending whatsapp message: {e}')
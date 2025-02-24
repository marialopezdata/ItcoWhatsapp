import logging
import os
import azure.functions as func
import json
import requests
import io
from langchain.chat_models import AzureChatOpenAI
from datetime import datetime
from pytz import timezone
from azure.cosmos import CosmosClient



from langchain.schema import (
    AIMessage,
    HumanMessage,
    SystemMessage
)
from utils.utils import Text
gpt_val = os.environ["KeyVaultGPT"]
os.environ["OPENAI_API_KEY"]=gpt_val
os.environ["OPENAI_API_BASE"]="https://pocsdata.openai.azure.com/"
os.environ["OPENAI_API_TYPE"]="azure"
os.environ["OPENAI_API_VERSION"]="2023-05-15"


# Token de verificación para WhatsApp Business Account
whatsapp_token = os.environ.get("WhatsappToken", "")


def clasificator(question, llm):
    message = HumanMessage(content=f"""
           {Text} 
           Trata de resolver la siguiente pregunta: {question}""")
    
    resp = llm([message])
    
    return resp.content


def llm_model_definition(id_model,**kwargs):
    llm = AzureChatOpenAI(
        temperature = 0.0,
        # max_tokens= 30,
        deployment_name=id_model,**kwargs)
    
    logging.info(llm)
    
    return llm


def send_whatsapp_message(body, message):
    try:
        value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        phone_number_id = value.get("metadata", {}).get("phone_number_id")
        from_number = value.get("messages", [{}])[0].get("from")
        
        if not phone_number_id or not from_number:
            logging.error("Faltan datos para enviar el mensaje de WhatsApp.")
            return
        
        logging.info(f"phone_number_id: {phone_number_id}")
        logging.info(f"from_number: {from_number}")
        
        if '54911' in from_number:
            from_number = from_number.replace('54911', '5411', 1)
        
        url = f"https://graph.facebook.com/v15.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {whatsapp_token}",
            "Content-Type": "application/json",
        }
        data = {
            "messaging_product": "whatsapp",
            "to": from_number,
            "type": "text",
            "text": {"body": message},
        }
        
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        logging.info("Mensaje enviado correctamente a WhatsApp.")
    except requests.RequestException as e:
        logging.error(f"Error al enviar mensaje de WhatsApp: {e}")
    except Exception as e:
        logging.error(f"Error inesperado en send_whatsapp_message: {e}")



# Función para almacenar los mensajes entrantes y salientes (webhooks)
def create_json(message,content,created,message_body_response):
    try:        
        # Adicionar fecha de recepción del mensaje       
        receipt_date = datetime.fromtimestamp(int(message["timestamp"]))
        receipt_date = receipt_date.astimezone(timezone('America/Bogota'))
        receipt_date = receipt_date.strftime('%d-%m-%Y %H:%M')
        add_receipt_date = {"receipt_date": receipt_date}
        message.update(add_receipt_date)

        # Adicionar fecha de respuesta del mensaje
        response_date = datetime.fromtimestamp(int(created))
        logging.info (f"response_date: {response_date}")
        response_date = response_date.astimezone(timezone('America/Bogota'))
        logging.info (f"response_date2: {response_date}")
        response_date = response_date.strftime('%d-%m-%Y %H:%M')
        logging.info (f"response_date3: {response_date}")
        add_response_date = {"response_date": response_date}
        message.update(add_response_date)
        logging.info ("Entra fecha de respuesta del mensaje")

        # Si el blob no existe, crear uno nuevo y almacenar el mensaje inicial
        with io.StringIO() as file_body:
            if message["type"] == "audio":
                add_transcript = {"transcript": message_body_response}
                logging.info (add_transcript)
                message.update(add_transcript)
            initial_data = {
                "message_from_user": message,
                "message_to_user": {"text": content}                    
            }
            json.dump(initial_data, file_body, indent=4)
            # file_body.seek(0)
            # blob_client.upload_blob(file_body.read())
            save_to_cosmos_db(message, content)

    except Exception as e:
        logging.error(f'ERROR - save the Webhook: {e}')
        raise


# Función para guardar JSON en Cosmos DB con claves de partición
def save_to_cosmos_db(message, response):
    # Conexión a Cosmos DB
    db_endpoint = os.environ["COSMOS_ENDPOINT"]
    db_key = os.environ["COSMOS_KEY"]
    db_name = os.environ["COSMOS_DATABASE_NAME"]
    db_container = os.environ["COSMOS_CONTAINER_NAME"]

    try:        
        # Obtiene la referencia a la base de datos y al contenedor
        client = CosmosClient(db_endpoint, db_key)
        database = client.get_database_client(db_name)
        container = database.get_container_client(db_container)
                
        # Crea un documento con el mensaje y la respuesta
        document = {
            "id": message["id"],
            "from": message["from"],
            "message_from_user": message,
            "message_to_user": {"text": response},
        }
                
        # Inserta el documento en el contenedor de Cosmos DB
        container.create_item(document)
        
        logging.info(f"Guardado en Cosmos DB: {message['id']}")
        
    except Exception as e:
        logging.error(f"ERROR - Conexión a Cosmos DB: {e}")
        raise
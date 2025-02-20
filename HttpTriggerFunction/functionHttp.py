import logging
import os
import azure.functions as func
import json
import requests
from langchain.chat_models import AzureChatOpenAI

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
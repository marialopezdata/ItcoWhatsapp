import logging
import azure.functions as func
import json
import os
from .functionHttp import llm_model_definition, clasificator
import requests

# Token de verificación Facebook Business Webhook
verify_token = os.environ.get("VerifyToken", "")

# Token de verificación para WhatsApp Business Account
whatsapp_token = os.environ.get("WhatsappToken", "")

LANGUAGE = "es-SP"


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


def main(req: func.HttpRequest) -> func.HttpResponse:
    # sourcery skip: extract-method
    logging.info("Python HTTP trigger function processed a request.")
    try:
        logging.info(f"req.method:{req.method}")
        logging.info(f"req:{req}")
        if req.method == "GET":
            verify_tokenWA = req.params.get("hub.verify_token")
            if verify_token != verify_tokenWA:
                return func.HttpResponse("Verificación fallida", status_code=403)
            challenge = req.params.get("hub.challenge", "")
            return func.HttpResponse(challenge, status_code=200)
        
        body = req.get_json()
        value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        message = value.get("messages", [{}])[0]
        
        if not message or message.get("type") != "text":
            return func.HttpResponse("Evento de WhatsApp API no recibido", status_code=404)
        
        message_body_response = message["text"]["body"]
        logging.info(f"message_body_response: {message_body_response}")
        
        llm = llm_model_definition("pocsgptbase16")
        response_text = clasificator(message_body_response, llm)
        response = {"response": response_text}
        
        send_whatsapp_message(body, response_text)
        return func.HttpResponse(json.dumps(response), status_code=200)
        
    except json.JSONDecodeError:
        return func.HttpResponse("Error al procesar JSON", status_code=400)
    except Exception as e:
        logging.error(f"Error en la función principal: {e}")
        return func.HttpResponse(str(e), status_code=500)
import logging
import azure.functions as func
import json
import os
# from .functionHttp import llm_model_definition, clasificator, send_whatsapp_message
from . import functionHttp


# Token de verificación Facebook Business Webhook
verify_token = os.environ.get("VerifyToken", "")
LANGUAGE = "es-SP"

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
        
        llm = functionHttp.llm_model_definition("pocsgptbase16")
        response_text = functionHttp.clasificator(message_body_response, llm)
        response = {"response": response_text}
        
        functionHttp.send_whatsapp_message(body, response_text)
        return func.HttpResponse(json.dumps(response), status_code=200)
        
    except json.JSONDecodeError:
        return func.HttpResponse("Error al procesar JSON", status_code=400)
    except Exception as e:
        logging.error(f"Error en la función principal: {e}")
        return func.HttpResponse(str(e), status_code=500)
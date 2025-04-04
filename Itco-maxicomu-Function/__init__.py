import logging
import azure.functions as func
import json
import os
from . import functionHttp

# Token de verificación de Facebook Business Webhook
VERIFY_TOKEN = os.environ.get("VerifyToken", "")

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")
    try:
        if req.method == "GET":
            return handle_verification(req)
        
        body = req.get_json()
        logging.info(f"body: {json.dumps(body, indent=2)}")
        
        # Extraer valores del JSON recibido
        value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        
        # Se evalúa si el evento recibido contiene mensajes vacíos
        if "messages" not in value:
            logging.info("Evento no contiene mensajes, ignorado.")
            return func.HttpResponse("Evento sin mensajes, ignorado.", status_code=200)
        
        message = value.get("messages", [{}])[0]
        phone_number_id = value.get("metadata", {}).get("phone_number_id")
        from_number = message.get("from") if isinstance(message, dict) else None
        
        # Validaciones
        if not phone_number_id or not from_number:
            logging.error("Faltan datos esenciales para enviar el mensaje de WhatsApp.")
            return func.HttpResponse(
                json.dumps({"error": "Faltan datos esenciales"}), status_code=400
            )
        
        if not isinstance(message, dict) or message.get("type") != "text":
            return func.HttpResponse(
                json.dumps({"error": "Evento de WhatsApp API no válido"}), status_code=404
            )
        
        message_body_response = message.get("text", {}).get("body", "").strip()
        if not message_body_response:
            return func.HttpResponse(
                json.dumps({"error": "Mensaje de texto vacío"}), status_code=400
            )
        logging.info(f"message_body_response: {message_body_response}")
        
        # **Responde 200 antes de procesar la lógica pesada**
        response_data = {"status": "processing"}
        func.HttpResponse(json.dumps(response_data), status_code=200)
        # Obtener respuesta de OpenAI y enviar el mensaje
        response_text = functionHttp.openai_request(value)
        logging.info(f"response_text: {response_text}")
        functionHttp.send_whatsapp_message(body, response_text)
        return func.HttpResponse(json.dumps({"response": response_text}), status_code=200)
    except json.JSONDecodeError:
        return func.HttpResponse(json.dumps({"error": "Error al procesar JSON"}), status_code=400)
    except KeyError as e:
        logging.error(f"Clave faltante en JSON: {e}")
        return func.HttpResponse(json.dumps({"error": f"Clave faltante: {str(e)}"}), status_code=400)
    except Exception as e:
        logging.exception("Error inesperado en la función principal")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500)

def handle_verification(req: func.HttpRequest) -> func.HttpResponse:
    """ Maneja la verificación del Webhook de WhatsApp Business API """
    verify_token_wa = req.params.get("hub.verify_token")
    challenge = req.params.get("hub.challenge", "")

    if VERIFY_TOKEN != verify_token_wa:
        return func.HttpResponse(json.dumps({"error": "Verificación fallida"}), status_code=403)

    return func.HttpResponse(challenge, status_code=200)

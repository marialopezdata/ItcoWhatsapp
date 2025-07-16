import json
import logging
import azure.functions as func
from . import functionComunicados
import utils.azure_clients as azure_clients

def main(req: func.HttpRequest) -> func.HttpResponse:
    """Procesa las solicitudes de mensajes del webhook de Meta."""
    logging.info('Ejecutando función de envío proactivo de WhatsApp')

    try:
        
        body = req.get_json()
        
        logging.info(f"body: {json.dumps(body, indent=2)}")
        
        communications = body.get("communication", [])
        
        contactos = functionComunicados.get_active_phone_numbers()
        
        for item in communications:
            
            logging.info(f"Enviando a: {contactos}")
            texto = item.get("texto", "")
            imagen_url = item.get("img", "")
        
            if not isinstance(texto, str) or not texto:
                return func.HttpResponse("Texto inválido", status_code=400)

            if not isinstance(imagen_url, str) or not imagen_url:
                return func.HttpResponse("Imagen inválida", status_code=400)

            functionComunicados.send_whatsapp_message(contactos, texto, imagen_url)

        return func.HttpResponse("Envío ejecutado correctamente", status_code=200)

    except Exception as e:
        logging.error(f"Error en ejecución: {e}")
        return func.HttpResponse("Error al ejecutar envío", status_code=500)


def handle_verification(req: func.HttpRequest) -> func.HttpResponse:
    """ Maneja la verificación del Webhook de WhatsApp Business API """
    try:
        secret_verify_token = azure_clients.get_secrets("webhook-token") 
        
        verify_token_wa = req.params.get("hub.verify_token")
        challenge = req.params.get("hub.challenge", "")
        
        if secret_verify_token != verify_token_wa:
            return func.HttpResponse(json.dumps({"error": "Verificación fallida"}), status_code=403)
        
        return func.HttpResponse(challenge, status_code=200)
    except Exception as e:
        logging.error(f"ERROR - getting greetings: {e}")
        raise

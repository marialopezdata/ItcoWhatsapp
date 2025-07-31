import json
import logging
import azure.functions as func
from . import functionComunicados
import utils.azure_clients as azure_clients


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Procesa las solicitudes de mensajes del webhook de Meta."""
    logging.info('Ejecutando función de envío proactivo de WhatsApp')
    
    try:
        contactos = functionComunicados.get_active_phone_numbers()  
        body = req.get_json()
        
        logging.info(f"body: {json.dumps(body, indent=2)}")
        
        communications = body.get("communication", [])              
        errores_totales = []
        
        for item in communications:            
            logging.info(f"Enviando a: {contactos}")
            template_name = item.get("template", "")
            texto = item.get("texto", "")
            header_url = item.get("header")
            url_button = item.get("button")
            
            if template_name is not None and not isinstance(template_name, str):
                return func.HttpResponse("Template inválido", status_code=400)
            
            if texto is not None and not isinstance(texto, str):
                return func.HttpResponse("Texto inválido", status_code=400)
            
            if header_url is not None and not isinstance(header_url, str):
                return func.HttpResponse("URL header inválida", status_code=400)
            
            if url_button is not None and not isinstance(url_button, str):
                return func.HttpResponse("URL botón inválida", status_code=400)
            
            errores = functionComunicados.send_whatsapp_message(contactos, template_name, texto, header_url, url_button)
            errores_totales.extend(errores)
            
        if errores_totales:
            logging.warning(f"Envío completado con errores: {errores_totales}")
            return func.HttpResponse(
                json.dumps({"mensaje": "Algunos envíos fallaron", "errores": errores_totales}, indent=2),
                status_code=207,
                mimetype="application/json"
            )

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

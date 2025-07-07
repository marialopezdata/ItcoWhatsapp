import os
import json
import logging
import azure.functions as func
from . import functionComunicados
from utils.azure_clients import get_secrets

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.') 
    try:
        if req.method == "GET":
            return handle_verification(req)
        
        #Llamada a función principal
        ejecucion = functionComunicados.read_announcements()
        
        if(ejecucion == "No hay mensajes activos"):
            return func.HttpResponse("Error",status_code=500)           
        else:
            lista_contactos = functionComunicados.get_active_phone_numbers()
            logging.info(f"lista_contactos:{lista_contactos}")
            functionComunicados.send_whatsapp_message(lista_contactos, ejecucion)
            return func.HttpResponse(ejecucion,status_code=200)
        
    except Exception as e:
        logging.error(f'ERROR - ejecución: {e}')
        return func.HttpResponse("Falla",status_code=500)
    
def handle_verification(req: func.HttpRequest) -> func.HttpResponse:
    """ Maneja la verificación del Webhook de WhatsApp Business API """
    secret_verify_token = get_secrets("webhook-token") 
    verify_token_wa = req.params.get("hub.verify_token")
    challenge = req.params.get("hub.challenge", "")

    if secret_verify_token != verify_token_wa:
        return func.HttpResponse(json.dumps({"error": "Verificación fallida"}), status_code=403)

    return func.HttpResponse(challenge, status_code=200)

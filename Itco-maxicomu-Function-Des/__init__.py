import logging
import azure.functions as func
import json
from . import functionHttp
import utils.azure_clients as azure_clients


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")
    try:
        if req.method == "GET":
            return handle_verification(req)
        
        body = req.get_json()
        logging.info(f"body: {json.dumps(body, indent=2)}")
        
        # Extraer valores del JSON recibido
        value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        
        statuses = value.get("statuses", [])
        if statuses:
            for status in statuses:
                functionHttp.update_conversation_pricing_from_status(status)

        # Si solo llegaron statuses, termina aquí
        if "messages" not in value:
            logging.info("Solo llegaron statuses (sin mensajes), procesado correctamente.")
            return func.HttpResponse("Solo statuses procesados.", status_code=200)
        
        # # Se evalúa si el evento recibido contiene mensajes vacíos
        # if "messages" not in value:            
        #     logging.info("Evento no contiene mensajes, ignorado.")
        #     return func.HttpResponse("Evento sin mensajes, ignorado.", status_code=200)
        
        message = value.get("messages", [{}])[0]
        phone_number_id = value.get("metadata", {}).get("phone_number_id")
        from_number = message.get("from") if isinstance(message, dict) else None
        
        # Validaciones
        if not phone_number_id or not from_number:
            logging.error("Faltan datos esenciales para enviar el mensaje de WhatsApp.")
            return func.HttpResponse(
                json.dumps({"error": "Faltan datos esenciales"}), status_code=400
            )        
        
        # Iterar todos los mensajes recibidos
        for msg in value.get("messages", []):
            msg_type = msg.get("type")
            if msg_type not in {"text", "interactive"}:
                functionHttp.send_whatsapp_message(
                    body,
                    "Lo sentimos, solo puedo entender mensajes de texto o botones. Por favor intenta nuevamente.",
                    interactive=False
                )
                # Responde solo una vez y termina
                return func.HttpResponse(
                    json.dumps({"error": f"Tipo de mensaje no soportado: {msg_type}"}),
                    status_code=400
                )

        # Si todos eran válidos, continuar con el procesamiento normal
        message = value["messages"][0]       
        
        # Obtener el contenido del mensaje según el tipo
        message_type = message.get("type")
        message_body_response = ""
        # button_id = None  # Inicializa para uso posterior si aplica

        if message_type == "text":
            message_body_response = message.get("text", {}).get("body", "").strip()

        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            interactive_type = interactive.get("type")

            if interactive_type == "button_reply":
                message_body_response = interactive.get("button_reply", {}).get("id")

            elif interactive_type == "list_reply":
                message_body_response = interactive.get("list_reply", {}).get("title", "").strip()
                button_id = interactive.get("list_reply", {}).get("id")  # También puede tener `id`

        if not message_body_response:
            return func.HttpResponse(
                json.dumps({"error": "Mensaje vacío o no válido"}), status_code=400
            )
        
        if not message_body_response:
            return func.HttpResponse(
                json.dumps({"error": "Mensaje de texto vacío"}), status_code=400
            )
        
        # Obtener respuesta de OpenAI y enviar el mensaje
        response_text = functionHttp.openai_request(value)

        if response_text.get("type") == "interactive":
            functionHttp.send_whatsapp_message(body, response_text["content"], interactive=True)
        else:
            functionHttp.send_whatsapp_message(body, response_text["content"])
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
    secret_verify_token = azure_clients.get_secrets("webhook-token") 
    verify_token_wa = req.params.get("hub.verify_token")
    challenge = req.params.get("hub.challenge", "")
    
    if secret_verify_token != verify_token_wa:
        return func.HttpResponse(json.dumps({"error": "Verificación fallida"}), status_code=403)
    return func.HttpResponse(challenge, status_code=200)
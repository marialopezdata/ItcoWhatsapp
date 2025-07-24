import logging
import azure.functions as func
import json
from . import functionHttp
import utils.azure_clients as azure_clients


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")
    try:
        type_error = True
        if req.method == "GET":
            return handle_verification(req)

        body = req.get_json()
        logging.info(f"body: {json.dumps(body, indent=2)}")

        # Extraer valor principal del JSON
        value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        
        statuses = value.get("statuses", [])

        # Procesar estados de mensajes
        for status in statuses:
            functionHttp.update_conversation_pricing_from_status(status)
            

        # Si no hay mensajes, terminar
        messages = value.get("messages", [])
        if not messages:
            type_error = False
            logging.info("Solo llegaron statuses (sin mensajes), procesado correctamente.")
            return func.HttpResponse("Solo statuses procesados.", status_code=200)            

        message = messages[0]
        phone_number_id = value.get("metadata", {}).get("phone_number_id")
        from_number = message.get("from") if isinstance(message, dict) else None

        # Validaciones de datos esenciales
        if not phone_number_id or not from_number:
            logging.error("Faltan datos esenciales para enviar el mensaje de WhatsApp.")
            return func.HttpResponse(
                json.dumps({"error": "Faltan datos esenciales"}), status_code=400
            )

        # Validar tipo de mensaje permitido
        msg_type = message.get("type")
        if msg_type not in {"text", "interactive"} and type_error:
            response_text ={
                "type": "text",
                "content": "Lo sentimos, solo puedo entender mensajes de texto o botones. Por favor intenta nuevamente."
            }
            
            functionHttp.send_whatsapp_message(
                body,
                response_text["content"],
                interactive=False
            )

            return func.HttpResponse(
                json.dumps({"warning": f"Tipo de mensaje no soportado: {msg_type}"}),
                status_code=200  # ← importante devolver 200 para evitar reintentos
            )
            
            # single_msg_body = body.copy()
            # single_msg_body["entry"][0]["changes"][0]["value"]["messages"] = [message]
            # logging.info(f"single_msg_body:{single_msg_body}")
            # functionHttp.send_whatsapp_message(
            #     single_msg_body,
            #     "Lo sentimos, solo puedo entender mensajes de texto o botones. Por favor intenta nuevamente.",
            #     interactive=False
            # )
            # return func.HttpResponse(
            #     json.dumps({"error": f"Tipo de mensaje no soportado: {msg_type}"}),
            #     status_code=400
            # )

        # Obtener contenido del mensaje según tipo
        message_body_response = ""
        if msg_type == "text":
            message_body_response = message.get("text", {}).get("body", "").strip()
        elif msg_type == "interactive":
            interactive = message.get("interactive", {})
            interactive_type = interactive.get("type")
            if interactive_type == "button_reply":
                message_body_response = interactive.get("button_reply", {}).get("id", "").strip()
            elif interactive_type == "list_reply":
                message_body_response = interactive.get("list_reply", {}).get("title", "").strip()

        if not message_body_response:
            return func.HttpResponse(
                json.dumps({"error": "Mensaje vacío o no válido"}), status_code=400
            )

        # Procesar con OpenAI
        response_text = functionHttp.openai_request(value)
        functionHttp.send_whatsapp_message(
            body,
            response_text["content"],
            interactive=response_text.get("type") == "interactive"
        )
        return func.HttpResponse(json.dumps({"response": response_text}), status_code=200)
    # try:
    #     if req.method == "GET":
    #         return handle_verification(req)
        
    #     body = req.get_json()
    #     logging.info(f"body: {json.dumps(body, indent=2)}")
        
    #     # Extraer valores del JSON recibido
    #     value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        
    #     statuses = value.get("statuses", [])
    #     if statuses:
    #         for status in statuses:
    #             functionHttp.update_conversation_pricing_from_status(status)

    #     # Si solo llegaron statuses, termina aquí
    #     if "messages" not in value:
    #         logging.info("Solo llegaron statuses (sin mensajes), procesado correctamente.")
    #         return func.HttpResponse("Solo statuses procesados.", status_code=200)
        
        
    #     message = value.get("messages", [{}])[0]
    #     phone_number_id = value.get("metadata", {}).get("phone_number_id")
    #     from_number = message.get("from") if isinstance(message, dict) else None
        
    #     # Validaciones
    #     if not phone_number_id or not from_number:
    #         logging.error("Faltan datos esenciales para enviar el mensaje de WhatsApp.")
    #         return func.HttpResponse(
    #             json.dumps({"error": "Faltan datos esenciales"}), status_code=400
    #         )        
        
    #     # Iterar todos los mensajes recibidos
    #     if from_number:
    #         msg_type = message.get("type")
    #         if msg_type not in {"text", "interactive"}:
    #             single_msg_body = body.copy()
    #             single_msg_body["entry"][0]["changes"][0]["value"]["messages"] = [message]                
                
    #             functionHttp.send_whatsapp_message(
    #                 single_msg_body,
    #                 "Lo sentimos, solo puedo entender mensajes de texto o botones. Por favor intenta nuevamente.",
    #                 interactive=False
    #             )
    #             # Responde solo una vez y termina
    #             return func.HttpResponse(
    #                 json.dumps({"error": f"Tipo de mensaje no soportado: {msg_type}"}),
    #                 status_code=400
    #             )

    #     # Si todos eran válidos, continuar con el procesamiento normal
    #     message = value["messages"][0]       
        
    #     # Obtener el contenido del mensaje según el tipo
    #     message_type = message.get("type")
    #     message_body_response = ""
    #     # button_id = None  # Inicializa para uso posterior si aplica

    #     if message_type == "text":
    #         message_body_response = message.get("text", {}).get("body", "").strip()

    #     elif message_type == "interactive":
    #         interactive = message.get("interactive", {})
    #         interactive_type = interactive.get("type")

    #         if interactive_type == "button_reply":
    #             message_body_response = interactive.get("button_reply", {}).get("id")

    #         elif interactive_type == "list_reply":
    #             message_body_response = interactive.get("list_reply", {}).get("title", "").strip()
    #             button_id = interactive.get("list_reply", {}).get("id")  # También puede tener `id`

    #     if not message_body_response:
    #         return func.HttpResponse(
    #             json.dumps({"error": "Mensaje vacío o no válido"}), status_code=400
    #         )
        
    #     if not message_body_response:
    #         return func.HttpResponse(
    #             json.dumps({"error": "Mensaje de texto vacío"}), status_code=400
    #         )
        
    #     # Obtener respuesta de OpenAI y enviar el mensaje
    #     response_text = functionHttp.openai_request(value)

    #     if response_text.get("type") == "interactive":
    #         functionHttp.send_whatsapp_message(body, response_text["content"], interactive=True)
    #     else:
    #         functionHttp.send_whatsapp_message(body, response_text["content"])
    #     return func.HttpResponse(json.dumps({"response": response_text}), status_code=200)
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
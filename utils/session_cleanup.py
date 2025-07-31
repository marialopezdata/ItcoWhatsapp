# utils/session_cleanup.py
from datetime import datetime, timedelta, timezone
# import utils.azure_clients as azure_clients
# import utils.utils as utils
# import threading
# import requests
import logging
# import time
import os

time_hours = int(os.environ.get("time_hours", 24))
# time_minutes = int(os.environ.get("time_minutes", 1))

def clean_old_sessions(container):
    """Cierra sesiones sin respuesta en 1 minuto o con más de 24 horas abiertas."""
    now = datetime.now(timezone.utc)
    # one_minute_ago = now - timedelta(minutes=time_minutes)
    one_day_ago = now - timedelta(hours=time_hours)

    query = "SELECT * FROM c WHERE c.sessionStatus = 'opened'"
    conversations = list(container.query_items(query, enable_cross_partition_query=True))

    for convo in conversations:
        messages = convo.get("messages", [])
        last_user_message = next((m for m in reversed(messages) if m["role"] == "user"), None)

        last_user_time = (
            datetime.fromisoformat(last_user_message["date"])
            if last_user_message
            else datetime.fromisoformat(convo["createdAt"])
        )
        created_at = datetime.fromisoformat(convo["createdAt"])

        # should_close = last_user_time < one_minute_ago or created_at < one_day_ago
        should_close = created_at < one_day_ago
        logging.info(f"Último mensaje del usuario: {last_user_time}, creación: {created_at}, ahora: {now}")
        if should_close:
            logging.info(f"Cerrando conversación {convo['id']} por inactividad o antigüedad.")
            convo["sessionStatus"] = "closed"
            convo["updatedAt"] = now.isoformat()
            # user_id = convo["userId"]
            # send_whatsapp_message_from_id(user_id, "Cerramos la sesión por inactividad. Si necesitas algo más, escríbenos.")
            container.upsert_item(convo)
            


# def send_whatsapp_message_from_id(user_id, text):
#     try:
#         logging.info("Se llamó a send_whatsapp_message_from_id")
#         phone_number_id = os.environ["phone_number_id"]
#         # whatsapp_token = azure_clients.get_secrets("whatsapp-token")
#         whatsapp_token = "EAATVIxJamLkBPFx54bbLzSpHKqrZCRjZB34Pgp2eisG8jvUhJUxa3lZA0amWn7V1bEOnhgZCqhucWzBNZALUUYYz7cJ954MRCqMgNOGSvA7lDiY4szazL8Sh6LtGcFsqM6kxEazUsAJcpGNnqAwZBLZBZCkZC8PvnNbQDhX81f7N4AcfU1vuEIvJ1JUKVpOIcMCj7DQZDZD"
#         secret_whatsapp_token = whatsapp_token.strip()
#         headers = {
#             "Authorization": f"Bearer {secret_whatsapp_token}",
#             "Content-Type": "application/json",
#         }
        
#         logging.info(f"headers:{headers}")
        
#         url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
#         logging.info(f"url:{url}")
        
#         payload = {
#             "messaging_product": "whatsapp",
#             "to": user_id,
#             "type": "text",
#             "text": {"body": text}
#         }
#         logging.info(f"payload:{payload}")
#         logging.info(f"Enviando mensaje a: {user_id}")
        
#         try:
#             response = requests.post(url, json=payload, headers=headers)
#             response.raise_for_status()
#             logging.info(f"Mensaje de cierre enviado a {user_id}: {response.status_code} - {response.text}")
#         except requests.exceptions.HTTPError as http_err:
#             logging.error(f"Error HTTP al enviar mensaje: {http_err} - {response.text}")
#         except Exception as e:
#             logging.error(f"Error general al enviar mensaje: {e}")
#     except Exception as e:
#         logging.error(f"Error al enviar mensaje por inactividad: {e}")




# def schedule_inactivity_check(user_id, conversation_id, wait_minutes=5):
#     def wait_and_close():
#         logging.info(f"Esperando {wait_minutes} minutos para revisar inactividad de {user_id}...")
#         time.sleep(wait_minutes * 60)  # espera en segundos

#         container = azure_clients.get_cosmos_container()
#         conversation = utils.get_conversation(container, user_id)
        
#         if not conversation or conversation["id"] != conversation_id:
#             logging.info("La conversación ya cambió o fue cerrada.")
#             return
        
#         last_msg = conversation["messages"][-1]
#         if last_msg["role"] == "assistant":
#             logging.info("No hay nueva respuesta del usuario. Cerrando sesión.")
            
#             # Marcar como cerrada
#             conversation["sessionStatus"] = "closed"
#             utils.save_conversation(container, conversation)

#             # Enviar mensaje de cierre
#             send_whatsapp_message_from_id(user_id, "Cerramos la sesión por inactividad. Si necesitas algo más, escríbenos.")
#         else:
#             logging.info("El usuario respondió. No se cierra sesión.")
    
#     threading.Thread(target=wait_and_close).start()
    


# def check_user_inactivity(conversation, now=None, threshold_minutes=1):
#     """
#     Cierra la conversación si el último mensaje del usuario fue hace más de `threshold_minutes`.
#     Retorna True si la conversación fue cerrada.
#     """
#     now = now or datetime.now(timezone.utc)
#     messages = conversation.get("messages", [])
    
#     # Buscar el último mensaje del usuario
#     last_user_message = next((m for m in reversed(messages) if m["role"] == "user"), None)
    
#     if not last_user_message:
#         return False  # No hay mensaje del usuario aún
    
#     last_user_time = datetime.fromisoformat(last_user_message.get("timestamp"))
    
#     if now - last_user_time > timedelta(minutes=threshold_minutes):
#         logging.info(f"Sesión {conversation['id']} cerrada por inactividad de más de {threshold_minutes} minutos.")
#         conversation["sessionStatus"] = "closed"
#         conversation["updatedAt"] = now.isoformat()
#         return True
    
#     return False
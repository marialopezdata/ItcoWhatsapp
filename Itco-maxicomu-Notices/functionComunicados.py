import os
import io
import logging
import pandas as pd
import requests
import time
from datetime import datetime, timezone
import utils.azure_clients as azure_clients
import utils.utils as utils
import utils.session_cleanup as clean

# Conexión a Whatsapp
whatsapp_token = "Bearer EAATVIxJamLkBPFx54bbLzSpHKqrZCRjZB34Pgp2eisG8jvUhJUxa3lZA0amWn7V1bEOnhgZCqhucWzBNZALUUYYz7cJ954MRCqMgNOGSvA7lDiY4szazL8Sh6LtGcFsqM6kxEazUsAJcpGNnqAwZBLZBZCkZC8PvnNbQDhX81f7N4AcfU1vuEIvJ1JUKVpOIcMCj7DQZDZD"
# whatsapp_token = azure_clients.get_secrets("whatsapp-token")

# Definir tiempo máximo de conversación activa (24 horas)
time_hours = int(os.environ.get("time_hours", 24))


def get_active_phone_numbers():  
    """Obtiene una lista de números de teléfono de contactos activos desde un archivo de Excel en Azure Blob Storage."""
    try:         
        # Obtener una referencia al contenedor
        blob_container = azure_clients.get_blob_container("storage_container_basecono")
        blob_client = blob_container.get_blob_client("comunicados/contactos.xlsx")
        
        # Descargar el contenido del archivo        
        blob_data = blob_client.download_blob()
        
        # Cargar el contenido del blob en un DataFrame de pandas
        excel_bytes = io.BytesIO(blob_data.readall())
        df = pd.read_excel(excel_bytes)        
        
        # Filtrar filas donde ENVIAR sea 'S'
        df_activo = df[df['ENVIAR'].astype(str).str.upper() == 'S']
        
        # Obtener la lista de números de teléfono
        telefonos = df_activo['TELEFONO'].astype(str).tolist()
        
        return telefonos
    
    except Exception as e:
        logging.error(f"ERROR - obteniendo contactos: {e}")
        raise


def templates_metadata(template_name: str):
    """Obtiene la información de la metadata de las plantillas configuradas en Meta."""
    try:
        # Obtener una referencia al contenedor
        blob_container = azure_clients.get_blob_container("storage_container_basecono")
        blob_client = blob_container.get_blob_client("comunicados/metadataComunicados.xlsx")
        
        # Descargar el contenido del archivo        
        blob_data = blob_client.download_blob()
        
        # Cargar el contenido del blob en un DataFrame de pandas
        excel_bytes = io.BytesIO(blob_data.readall())
        df = pd.read_excel(excel_bytes)
        
        # Filtrar filas donde el nombre del template coincida
        df_activo = df[df['name'].astype(str).str.upper() == template_name.upper()]
        
        # Eliminar columnas completamente vacías (por limpieza general)
        df_activo = df_activo.dropna(axis=1, how='all')
        
        return df_activo

    except Exception as e:
        logging.error(f"ERROR - obteniendo las plantillas: {e}")
        raise


def build_template_from_metadata(contact, template_name=None, texto=None, header_url=None, button_value=None):
    """
    Construye dinámicamente el payload para enviar una plantilla de WhatsApp 
    según los campos definidos en el archivo de metadataComunicados.xlsx.

    Args:
        contact (str): Número de teléfono.
        template_name (str): Nombre de la plantilla.
        texto (str): Texto del cuerpo (body).
        header_url (str): URL del encabezado si aplica (imagen, video, documento).
        button_value (str): URL o número de teléfono para botón, si aplica.

    Returns:
        dict: Payload del mensaje para la API de WhatsApp.
    """
    try:
        df_activo = templates_metadata(template_name)

        if df_activo.empty:
            raise ValueError(f"No se encontró metadata para el template: {template_name}")

        row = df_activo.iloc[0]
        components = []

        # HEADER
        header_type = row.get("header")
        if pd.notna(header_type) and header_url:
            components.append({
                "type": "header",
                "parameters": [
                    {
                        "type": header_type.lower(),  # image, video, document
                        header_type.lower(): {
                            "link": header_url
                        }
                    }
                ]
            })

        # BODY
        parameter = row.get("body")
        if pd.notna(parameter) and texto:
            components.append({
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "parameter_name": parameter,
                        "text": texto
                    }
                ]
            })

        # FOOTER (solo se incluye si está definido, aunque no requiere parámetros)
        if pd.notna(row.get("footer")):
            components.append({
                "type": "footer",
                "parameters": []
            })

        # BUTTON
        button_type = row.get("buttons")
        if pd.notna(button_type) and button_value:
            button_component = {
                "type": "button",
                "index": 0,
                "parameters": []
            }

            if button_type == "url":
                button_component["sub_type"] = "url"
                button_component["parameters"].append({
                    "type": "text",
                    "text": button_value
                })

            elif button_type == "phone_number":
                button_component["sub_type"] = "phone_number"
                button_component["parameters"].append({
                    "type": "text",
                    "text": button_value
                })

            components.append(button_component)

        # Construcción final del payload
        payload = {
            "messaging_product": "whatsapp",
            "to": contact,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "es_CO"},
                "components": components
            }
        }

        return payload
    except Exception as e:
        logging.error(f"ERROR - armando plantilla: {e}")
        raise


def send_whatsapp_message(contacts, template_name, texto, header_url=None, button_value=None):
    """Envía un mensaje de WhatsApp a varios contactos usando la API de Meta."""
    errores = []
    try:
        now = datetime.now(timezone.utc)
        container = azure_clients.get_cosmos_container()
        na = ["No Aplica"]
        
        # clean.clean_old_sessions(container)
        
        headers = {
            "Authorization": whatsapp_token,
            "Content-Type": "application/json",
        }       
        
        phone_number_id = os.environ["phone_number_id"]
        
        url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
        
        for contact in contacts:
            contact = contact.strip()  # Elimina espacios o saltos de línea

            if not contact:
                logging.info(f"no contact")
                continue  # Evita enviar si el contacto está vacío
            
            conversation = utils.get_conversation(container, contact)

            if conversation:
                conversation_history = conversation["messages"]
                
                if utils.should_close_conversation(conversation, time_hours):
                    logging.info("Conversación cerrada o expirada. Se crea una nueva.")
                    conversation["sessionStatus"] = "closed"
                    utils.save_conversation(container, conversation)                    
            
            conversation = utils.initialize_conversation(contact, "user_name")
            
            conversation_history = conversation["messages"]

            payload = build_template_from_metadata(
                contact,
                template_name,
                texto,
                header_url,
                button_value
            )            
            
            logging.info(f"Enviando mensaje a: {contact}")
            response = requests.post(url, headers=headers, json=payload)
            logging.info(f"response content: {response.content}")
            logging.info(f"response status code: {response.status_code}")
            content = f"{texto} - encabezado: {header_url} - botón: {button_value}"
            try:
                content_response = response.json()
                message_id = content_response.get("messages", [{}])[0].get("id", "sin_id")
            except Exception as parse_error:
                logging.error(f"Error parsing response: {parse_error}")
                errores.append({
                    "contacto": contact,
                    "error": f"Error parseando respuesta: {str(parse_error)}",
                    "status_code": response.status_code,
                    "content": response.content.decode("utf-8", errors="ignore")
                })
                continue
            
            if response.status_code != 200:
                logging.error(f"Falló el envío a {contact}. Status: {response.status_code}. Content: {response.content}")
                errores.append({
                    "contacto": contact,
                    "status_code": response.status_code,
                    "content": response.content.decode("utf-8", errors="ignore")
                })
                continue  # salta al siguiente contacto
            else:
                utils.add_message(conversation_history, "assistant", content, message_id, "campaña", na, na)
                
                # -------------------------------
                # 2. Enviar botones de aceptación/rechazo de la política
                # -------------------------------
                response_content = {
                    "type": "button",
                    "body": {
                        "text": "¿Aceptas la política de datos personales?"
                    },
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {
                                    "id": "accept",
                                    "title": "Aceptar"
                                }
                            },
                            {
                                "type": "reply",
                                "reply": {
                                    "id": "reject",
                                    "title": "Rechazar"
                                }
                            }
                        ]
                    }
                }

                payload_buttons = {
                    "messaging_product": "whatsapp",
                    "to": contact,
                    "type": "interactive",
                    "interactive": response_content
                }

                time.sleep(5)  # Pequeño delay entre mensajes

                try:
                    logging.info(f"Enviando a: {contact}")
                    response_buttons = requests.post(url, headers=headers, json=payload_buttons)
                    logging.info(f"response buttons status: {response_buttons.status_code}")
                    logging.info(f"response buttons content: {response_buttons.content}")

                    if response_buttons.status_code != 200:
                        errores.append({
                            "contacto": contact,
                            "status_code": response_buttons.status_code,
                            "content": response_buttons.content.decode("utf-8", errors="ignore")
                        })

                    else:
                        buttons_response = response_buttons.json()
                        message_id_btn = buttons_response.get("messages", [{}])[0].get("id", "sin_id")
                        content_btn = "¿Aceptas la política de datos personales?"
                        utils.add_message(conversation_history, "assistant", content_btn, message_id_btn, "politica", na, na)

                except Exception as err:
                    logging.error(f"Error enviando botones: {err}")
                    errores.append({
                        "contacto": contact,
                        "error": f"Error enviando botones: {str(err)}"
                    })
                    continue

                # Guardar conversación actualizada
                utils.save_conversation(container, {
                    "id": conversation["id"],
                    "userId": conversation["userId"],
                    "userName": conversation["userName"],
                    "createdAt": now.isoformat(),
                    "updatedAt": now.isoformat(),
                    "messages": conversation_history,
                    "sessionStatus": conversation["sessionStatus"]
                })

                time.sleep(1)  # Delay entre contactos para evitar throttling
    except Exception as e:
        logging.error(f'ERROR - sending whatsapp message: {e}')
        errores.append({"error": str(e)})
    
    return errores
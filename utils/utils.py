import io
import uuid
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone
import utils.azure_clients as azure_clients


def get_conversation(container, userId):
    """Obtiene las conversaciones almacenadas en la BD para cada usuario."""
    try:
        # Ordenar por createdAt DESC y tomar el primero
        query = "SELECT * FROM c WHERE c.userId = @userId ORDER BY c.createdAt DESC OFFSET 0 LIMIT 1"
        
        # Ejecutar la consulta con parámetros
        existing_conversations = list(
            container.query_items(
                query=query,
                parameters=[{"name": "@userId", "value": userId}],
                enable_cross_partition_query=True
            )
        )        
        return existing_conversations[0] if existing_conversations else None    
    except Exception as e:
        logging.error(f'ERROR - getting conversation in database: {e}')
        raise


def should_close_conversation(conversation, time_hours):
    """Determina si debe cerrarse una conversación existente."""
    try:
        now = datetime.now(timezone.utc)
        created_at = datetime.fromisoformat(conversation["createdAt"])
        expired = (now - created_at) >= timedelta(hours=time_hours)
        manually_closed = conversation["sessionStatus"] == "closed"
        return expired or manually_closed
    except Exception as e:
        logging.error(f"ERROR - closing conversation: {e}")
        raise


def should_close_by_inactivity(conversation, time_minutes):
    """Retorna True si han pasado más de time_minutes desde el último mensaje del usuario."""
    now = datetime.now(timezone.utc)
    if not conversation.get("messages"):
        return False
    for msg in reversed(conversation["messages"]):
        if msg["role"] == "user":
            last_user_time = datetime.fromisoformat(msg["date"])
            break
    else:
        return False  # No hay mensajes de usuario

    return (now - last_user_time) > timedelta(minutes=time_minutes)


def already_processed(conversation_history, message_id):
    """Determina si el mensaje ya fue procesado."""
    try:
        return any(msg.get("messageId") == message_id and msg["role"] == "assistant" for msg in conversation_history)
    except Exception as e:
        logging.error(f"ERROR - validating existing conversation: {e}")
        raise


def initialize_conversation(user_id, user_name):
    """Inicializa una nueva conversación."""
    try:
        now = datetime.now(timezone.utc)
        return {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "userName": user_name,
            "createdAt": now,
            "updatedAt": datetime(1900, 1, 1),
            "messages": [],
            "sessionStatus": "opened"
        }
    except Exception as e:
        logging.error(f"ERROR - initializing conversation: {e}")
        raise


def save_conversation(container, new_conversation_data):
    """Guarda la conversación en la Base de Datos."""
    try:
        if "messages" in new_conversation_data:
            new_conversation_data["totalCostUSD"] = calculate_total_cost(new_conversation_data)
        container.upsert_item(new_conversation_data)        
    except Exception as e:
        logging.error(f'ERROR - saving conversation in database: {e}')
        raise


def flatten_list(l):
    return [item for sublist in l for item in sublist] if any(isinstance(i, list) for i in l) else l


def add_message(history, role, content, message_id, msg_type, fuente, categories):
    """Adiciona un mensaje al historial."""
    try:
        fuente = flatten_list(fuente)
        categories = flatten_list(categories)
        now = datetime.now(timezone.utc)
        history.append({
            "role": role,
            "content": content,
            "date": now.isoformat(),
            "messageId": message_id,
            "typeMessage": msg_type,
            "fuente": fuente,
            "categories": categories
        })
    except Exception as e:
        logging.error(f"ERROR - adding message: {e}")
        raise


def process_webhook_pricing(value):
    """Extrae la información facturable de la conversación desde el webhook."""
    try:
        pricing = value.get("pricing", {})
        if pricing:
            return {
                "billable": pricing.get("billable", True),
                "category": pricing.get("category", "unknown"),
                "pricing_model": pricing.get("pricing_model", "CBP")
            }
    except Exception as e:
        logging.warning(f"No se pudo procesar el pricing: {e}")
    return {"billable": False, "category": "service", "pricing_model": "N/A"}


def whatsapp_pricing_usd():
    """Obtiene la información del costo de la conversación para hacer el cálculo."""
    try:
        # Obtener una referencia al contenedor
        blob_container = azure_clients.get_blob_container("storage_container_basecono")
        blob_client = blob_container.get_blob_client("comunicados/costos.xlsx")
        
        # Descargar el contenido del archivo        
        blob_data = blob_client.download_blob()
        
        # Cargar el contenido del blob en un DataFrame de pandas
        excel_bytes = io.BytesIO(blob_data.readall())
        df = pd.read_excel(excel_bytes) 
        
        return df
    except Exception as e:
        logging.error(f'ERROR - getting whatsapp pricing: {e}')
        raise


def calculate_pricing(user_id, pricing_category: str):
    """Calcula el costo de la conversación."""
    try:
        price = 0
        
        df = whatsapp_pricing_usd()
        
        if user_id.startswith("57"):
            country = "CO"
        else:
            country = "UNKNOWN"        
        
        # Filtrar filas donde encuentre el país
        df_filtered = df[
            (df['PAIS'].astype(str).str.upper() == country) & 
            (df['CATEGORIA'].astype(str).str.upper() == pricing_category.upper())
            ]
        
        if not df_filtered.empty:
            price = df_filtered['PRECIOUSD'].iloc[0]            
        else:
            logging.info("No se encontró un precio para esa combinación.")
            
        return price
    except Exception as e:
        logging.error(f'ERROR - calculating price: {e}')
        raise


def calculate_total_cost(doc: dict) -> float:
    """Suma el costo total de los mensajes de tipo assistant que tengan whatsappPricing."""
    try:
        total = sum(
            m.get("whatsappPricing", {}).get("cost_usd", 0)
            for m in doc.get("messages", [])
            if m.get("role") == "assistant" and m.get("whatsappPricing")
        )
        return round(total, 4)
    except Exception as e:
        logging.error(f"ERROR - calculando total conversación: {e}")
        return 0.0
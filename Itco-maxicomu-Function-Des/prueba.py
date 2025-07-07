# from azure.identity import DefaultAzureCredential
# from azure.keyvault.secrets import SecretClient
# import logging

# # URL del Key Vault
# key_vault_url = "https://itco-kv-pru-maxicomu-001.vault.azure.net/"

# # Autenticación con la identidad administrada
# credential = DefaultAzureCredential()

# print(f"credential:{credential}")

# # Cliente para consultar secretos
# client = SecretClient(vault_url=key_vault_url, credential=credential)

# # Obtener un secreto
# secret_name = "webhook-token"
# retrieved_secret = client.get_secret(secret_name)

# print(f"Valor del secreto: {retrieved_secret.value}")


#
# import requests
# import logging

# url = "https://graph.facebook.com/v17.0/490296914176806/messages"
# token = "EAAIk1I9ZB3CcBOZC61ZB1NuMu7j11K7hMym0ZANZC8EXnWw7q1XWKT751cdnY0Jnlr3bZBi6YRrsTv92ra2DHPsbDlkLbDtwXZA9nhZBdtoINnxJZBRRoEkAjXVxP75JFDkYGWLyDPxf5BxnKqzV0ri6ZAPYwS2UY95feqFBPVjh32PY2rteU9FWHNizQ6AdjZC3a2vjwZDZD"
# headers = {
#     "Authorization": f"Bearer {token}",
#     "Content-Type": "application/json"
# }
# payload = {
#     "messaging_product": "whatsapp",
#     "to": "573006577046",
#     "type": "text",
#     "text": {
#         "body": "¡Hola desde prueba directa con token correcto!"
#     }
# }

# response = requests.post(url, headers=headers, json=payload)
# print(response.status_code)
# print(response.text)


# import os
# import logging
# import requests
# import tempfile

# import azure.functions as func
# from office365.sharepoint.files.file import File
# from office365.sharepoint.client_context import ClientContext
# from office365.runtime.auth.client_credential import ClientCredential


# def send_whatsapp_image(to_phone: str, image_path: str, whatsapp_token: str, template_name: str):
#     """
#     Sends an image using the WhatsApp Business API via a template.

#     Parameters:
#     - to_phone (str): Recipient phone number with country code.
#     - image_path (str): Local file path to the image.
#     - whatsapp_token (str): Authorization token for WhatsApp API.
#     - template_name (str): Name of the approved WhatsApp template.

#     Returns:
#     - dict: Response from WhatsApp API.
#     """
#     url = "https://graph.facebook.com/v18.0/<YOUR_PHONE_NUMBER_ID>/messages"
#     headers = {
#         "Authorization": f"Bearer {whatsapp_token}",
#         "Content-Type": "application/json"
#     }

#     # Subir imagen primero (media upload)
#     media_url = "https://graph.facebook.com/v18.0/<YOUR_PHONE_NUMBER_ID>/media"
#     with open(image_path, 'rb') as img_file:
#         media_resp = requests.post(
#             media_url,
#             headers={"Authorization": f"Bearer {whatsapp_token}"},
#             files={"file": img_file},
#             data={"messaging_product": "whatsapp", "type": "image"}
#         )
#     media_id = media_resp.json().get("id")
#     if not media_id:
#         logging.error("Error uploading image to WhatsApp")
#         return media_resp.json()

#     # Enviar mensaje usando plantilla con imagen
#     payload = {
#         "messaging_product": "whatsapp",
#         "to": to_phone,
#         "type": "template",
#         "template": {
#             "name": template_name,
#             "language": {"code": "es_MX"},
#             "components": [{
#                 "type": "header",
#                 "parameters": [{
#                     "type": "image",
#                     "image": {"id": media_id}
#                 }]
#             }]
#         }
#     }

#     response = requests.post(url, headers=headers, json=payload)
#     return response.json()


# def process_sharepoint_images(ctx, relative_url, whatsapp_token, template_name, to_phone):
#     """
#     Descarga imágenes desde SharePoint y las envía vía WhatsApp usando una plantilla.

#     Returns:
#     - List[str]: Lista de nombres de archivos enviados.
#     """
#     sent_files = []

#     folder = ctx.web.get_folder_by_server_relative_url(relative_url)
#     files = folder.files
#     ctx.load(files)
#     ctx.execute_query()

#     for file in files:
#         file_name = file.properties['Name']
#         if not file_name.lower().endswith(('.jpg', '.jpeg', '.png')):
#             continue

#         logging.info(f"Descargando imagen de SharePoint: {file_name}")
#         file_url = f"{relative_url}/{file_name}"
#         response = File.open_binary(ctx, file_url)

#         # Guardar temporalmente
#         with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp:
#             tmp.write(response.content)
#             tmp_path = tmp.name

#         # Enviar imagen por WhatsApp
#         api_response = send_whatsapp_image(to_phone, tmp_path, whatsapp_token, template_name)
#         logging.info(f"WhatsApp API response: {api_response}")
#         sent_files.append(file_name)

#     return sent_files


# def main(req: func.HttpRequest) -> func.HttpResponse:
#     logging.info('Python HTTP trigger: SharePoint to WhatsApp process started.')

#     try:
#         sharepoint_site_url = os.environ["sharepoint_site_url"]
#         sharepoint_images_relativeurl = os.environ["sharepoint_images_relativeurl"]
#         sharepoint_clientid = os.environ["sharepoint_clientid"]
#         sharepoint_clientsecret = os.environ["sharepoint_clientsecret"]
#         whatsapp_token = os.environ["whatsapp_api_token"]
#         whatsapp_template = os.environ["whatsapp_template_name"]
#         whatsapp_phone = os.environ["whatsapp_recipient_phone"]

#         # SharePoint connection
#         credentials = ClientCredential(sharepoint_clientid, sharepoint_clientsecret)
#         ctx = ClientContext(sharepoint_site_url).with_credentials(credentials)

#         # Procesar imágenes
#         sent_images = process_sharepoint_images(
#             ctx=ctx,
#             relative_url=sharepoint_images_relativeurl,
#             whatsapp_token=whatsapp_token,
#             template_name=whatsapp_template,
#             to_phone=whatsapp_phone
#         )

#         return func.HttpResponse(
#             f"Imágenes enviadas por WhatsApp: {sent_images}",
#             status_code=200
#         )

#     except Exception as e:
#         logging.error(f"Error: {str(e)}")
#         return func.HttpResponse(
#             f"Error ejecutando la función: {str(e)}",
#             status_code=500
#         )


# import openai
# client = openai.AzureOpenAI(
#     api_key="bfdda20d9c6e482b90d58776750e3da9",
#     api_version="2023-05-15",
#     azure_endpoint="https://itco-oai-coed-pruebas-001.openai.azure.com/embeddings"
# )
# response = client.embeddings.create(
#     input=["Hola, ¿cómo estás?", "Este es un texto para probar embeddings."],
#     model="pru-maxi-embedding-small"
# )
# for i, data in enumerate(response.data):
#     print(f"Embedding {i}: {data.embedding[:5]}...")






# from azure.cosmos import CosmosClient
# from azure.identity import DefaultAzureCredential


# endpoint = "https://testcosmosjeff.documents.azure.com:443/"
# credential = DefaultAzureCredential()
# client = CosmosClient(endpoint, credential=credential)
# container = client.get_database_client("testjefferson").get_container_client("testjefferson")











# import logging
# from langchain.chat_models import ChatOpenAI
# from langchain.schema import HumanMessage
# from langchain.prompts import ChatPromptTemplate 
# from langchain_openai import AzureChatOpenAI 
# import os


# os.environ["OPENAI_API_KEY"]="bfdda20d9c6e482b90d58776750e3da9"
# os.environ["OPENAI_API_BASE"]="https://itco-oai-coed-pruebas-001.openai.azure.com/"
# os.environ["OPENAI_API_TYPE"]="azure"
# os.environ["OPENAI_API_VERSION"]="2023-05-15"

# def llm_model_definition(id_model,**kwargs):
#     # sourcery skip: inline-immediately-returned-variable
#     llm = AzureChatOpenAI(
#     temperature = 0.0,
#     # max_tokens= 30,
#     deployment_name=id_model,**kwargs)
    
#     return llm


# def openai_request(message, **kwargs):
#     try:
#         logging.info("Entro")

#         model = AzureChatOpenAI(
#             temperature=0.0, 
#             deployment_name="pru-maxi-chat", 
#             **kwargs, 
#             azure_endpoint="https://itco-oai-coed-pruebas-001.openai.azure.com/"
#             )

#         message = HumanMessage(
#             content=f"{message}"
#         )
#         response = model([message])

#         logging.info(f"Respuesta openAI 1: {response}")

#         return response

#     except Exception as e:
#         response = "Lo siento, OpenAI no está disponible en este momento. Por favor intente más tarde."
#         logging.error(f'ERROR - openai: {e}')




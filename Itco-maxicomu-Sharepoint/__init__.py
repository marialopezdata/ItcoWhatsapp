import os
import logging
import azure.functions as func

from office365.sharepoint.files.file import File
from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.client_credential import ClientCredential


from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

def process_sharepoint_folder(ctx, relative_url, container_client, file_extensions, blob_prefix):
    """
    Downloads files from a SharePoint folder and uploads them to an Azure Blob Storage container.

    Parameters:
    - ctx (ClientContext): Authenticated SharePoint client context.
    - relative_url (str): The SharePoint server-relative URL of the folder to read files from.
    - container_client (ContainerClient): The Azure Blob Storage container client used for uploads.
    - file_extensions (List[str]): A list of allowed file extensions to filter files to be uploaded.
    - blob_prefix (str): The folder path prefix to use when saving files into the blob container.

    Returns:
    - List[str]: A list of filenames that were successfully uploaded to Blob Storage.
    """
    uploaded_files = []

    # Access the folder and retrieve the file list
    folder = ctx.web.get_folder_by_server_relative_url(relative_url)
    files = folder.files
    ctx.load(files)
    ctx.execute_query()

    logging.info(f"Files found in SharePoint folder '{relative_url}': {len(files)}")

    for file in files:
        file_name = file.properties['Name']

        if not any(file_name.endswith(ext) for ext in file_extensions):
            continue  # Skip unsupported extensions
        
        logging.info(f"Downloading from SharePoint: {file_name}")
        file_url = f"{relative_url}/{file_name}"
        response = File.open_binary(ctx, file_url)

        # Upload to Blob Storage under the specified prefix
        storage_file_name = f"{blob_prefix}/{file_name}"
        blob_client = container_client.get_blob_client(storage_file_name)
        blob_client.upload_blob(response.content, overwrite=True)
        logging.info(f"Uploaded to Blob Storage: {storage_file_name}")
        uploaded_files.append(file_name)

    return uploaded_files

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger: SharePoint to Blob process started.')

    try:
        # Load configuration from environment variables
        sharepoint_site_url = os.environ["sharepoint_site_url"]
        sharepoint_basecono_relativeurl = os.environ["sharepoint_basecono_relativeurl"]
        sharepoint_saludo_relativeurl = os.environ["sharepoint_saludo_relativeurl"]
        sharepoint_difusion_relativeurl = os.environ["sharepoint_difusion_relativeurl"]
        sharepoint_images_relativeurl = os.environ["sharepoint_images_relativeurl"]
        sharepoint_clientid = os.environ["sharepoint_clientid"]
        sharepoint_clientsecret = os.environ["sharepoint_clientsecret"]
        storage_account_name = os.environ["storage_account_name"]
        storage_container_basecono = os.environ["storage_container_basecono"]
        
        # Connect to SharePoint using App Registration credentials
        credentials = ClientCredential(sharepoint_clientid, sharepoint_clientsecret)
        ctx = ClientContext(sharepoint_site_url).with_credentials(credentials)

        # Connect to Azure Blob Storage using managed identity
        account_url = f"https://{storage_account_name}.blob.core.windows.net"
        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
        container_client = blob_service_client.get_container_client(storage_container_basecono)
        container_client.get_container_properties()

        # Process folders
        # Excel Base Conocimiento
        uploaded_excels = process_sharepoint_folder(
            ctx=ctx,
            relative_url=sharepoint_basecono_relativeurl,
            container_client=container_client,
            file_extensions=[".xlsx"],
            blob_prefix="excel"
        )
        
        # Excel Comunicados
        uploaded_excels_comunicados = process_sharepoint_folder(
            ctx=ctx,
            relative_url=sharepoint_difusion_relativeurl,
            container_client=container_client,
            file_extensions=[".xlsx"],
            blob_prefix="comunicados"
        )

        # Files
        uploaded_texts = process_sharepoint_folder(
            ctx=ctx,
            relative_url=sharepoint_saludo_relativeurl,
            container_client=container_client,
            file_extensions=[".txt"],
            blob_prefix="plano"
        )
        
        # Img Comunicados
        uploaded_imgs = process_sharepoint_folder(
            ctx=ctx,
            relative_url=sharepoint_images_relativeurl,
            container_client=container_client,
            file_extensions=[".jpg", ".png"],
            blob_prefix="comunicados/piezas"
        )

        return func.HttpResponse(
            f"Files uploaded: {uploaded_excels}\n {uploaded_excels_comunicados}\n {uploaded_imgs}\n Text files uploaded: {uploaded_texts}",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Exception occurred: {str(e)}")
        return func.HttpResponse(
            f"Error executing function: {str(e)}",
            status_code=500
        )
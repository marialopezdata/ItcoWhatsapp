import logging
from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage
from langchain.prompts import ChatPromptTemplate 
from langchain_openai import AzureChatOpenAI 
import os


os.environ["OPENAI_API_KEY"]="bfdda20d9c6e482b90d58776750e3da9"
os.environ["OPENAI_API_BASE"]="https://itco-oai-coed-pruebas-001.openai.azure.com/"
os.environ["OPENAI_API_TYPE"]="azure"
os.environ["OPENAI_API_VERSION"]="2023-05-15"

def llm_model_definition(id_model,**kwargs):
    # sourcery skip: inline-immediately-returned-variable
    llm = AzureChatOpenAI(
    temperature = 0.0,
    # max_tokens= 30,
    deployment_name=id_model,**kwargs)
    
    return llm


def openai_request(message, **kwargs):
    try:
        logging.info("Entro")

        model = AzureChatOpenAI(
            temperature=0.0, 
            deployment_name="pru-maxi-chat", 
            **kwargs, 
            azure_endpoint="https://itco-oai-coed-pruebas-001.openai.azure.com/"
            )

        message = HumanMessage(
            content=f"{message}"
        )
        response = model([message])

        logging.info(f"Respuesta openAI 1: {response}")

        return response

    except Exception as e:
        response = "Lo siento, OpenAI no está disponible en este momento. Por favor intente más tarde."
        logging.error(f'ERROR - openai: {e}')




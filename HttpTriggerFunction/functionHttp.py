import logging
import os

from langchain.schema import (
    AIMessage,
    HumanMessage,
    SystemMessage
)

from langchain.chat_models import AzureChatOpenAI

import azure.functions as func
import json


gpt_val = os.environ["KeyVaultGPT"]
os.environ["OPENAI_API_KEY"]=gpt_val
os.environ["OPENAI_API_BASE"]="https://pocsdata.openai.azure.com/"
os.environ["OPENAI_API_TYPE"]="azure"
os.environ["OPENAI_API_VERSION"]="2023-05-15"
from utils.utils import Text


def clasificator(question, llm):
    message = HumanMessage(content=f"""
           {Text} 
           Trata de resolver la siguiente pregunta: {question}""")
    
    resp = llm([message])
    
    return resp.content


def llm_model_definition(id_model,**kwargs):
    llm = AzureChatOpenAI(
        temperature = 0.0,
        # max_tokens= 30,
        deployment_name=id_model,**kwargs)
    
    logging.info(llm)
    
    return llm
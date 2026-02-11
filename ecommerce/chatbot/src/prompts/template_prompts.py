from langchain_core.prompts import ChatPromptTemplate
# RAG용 답변 생성 프롬프트
RAG_ANSWER_TEMPLATE = ChatPromptTemplate.from_template("""
{system_prompt}
다음 문맥(Context)을 바탕으로 질문에 답변하세요:
{context}
질문: {question}
답변:
""")
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="e-commerce paltform")

@app.get("/")
def health_check():
    return {"status": "ok", "message": "서버가 RunPod에서 정상적으로 실행 중입니다!"}
from fastapi import FastAPI


app = FastAPI()


@app.get("/")
def root():
    return {"system": "on"}


@app.get("/")
def get_all_users():
    return "users"

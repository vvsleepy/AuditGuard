from fastapi import FastAPI
from pydantic import BaseModel

from .environment import AuditGuardEnvironment


app = FastAPI()
env = AuditGuardEnvironment()


class StepRequest(BaseModel):
    action: dict


@app.get("/")
def root() -> dict:
    return {"message": "AuditGuard API running 🚀"}


@app.get("/health")
def health() -> dict:
    return {"status": "healthy"}


@app.get("/state")
def state() -> dict:
    return {
        "task_id": env.state.task_id,
        "step_count": env.state.step_count,
        "max_steps": env.state.max_steps,
        "done": env.state.done,
    }


@app.post("/reset")
def reset() -> dict:
    observation = env.reset()
    return {
        "observation": observation,
        "info": {},
    }


@app.post("/step")
def step(payload: StepRequest) -> dict:
    observation, reward, done, info = env.step(payload.action)
    return {
        "observation": observation,
        "reward": round(reward, 2),
        "done": done,
        "info": info,
    }


def main() -> None:
    import uvicorn

    uvicorn.run("server.app:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()

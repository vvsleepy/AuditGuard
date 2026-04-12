import requests


class AuditGuardClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url

    def reset(self):
        return requests.post(f"{self.base_url}/reset", json={}).json()

    def step(self, action):
        return requests.post(f"{self.base_url}/step", json={"action": action}).json()

    def run_episode(self, agent):
        obs = self.reset()["observation"]
        done = False
        history = []

        while not done:
            action = agent(obs)
            response = self.step(action)
            history.append(response)
            obs = response["observation"]
            done = response["done"]

        return history

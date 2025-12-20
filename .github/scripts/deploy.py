import os

from huggingface_hub import HfApi

token = os.environ["HF_TOKEN"]
repo_id = "ArunKr/autonomy-labs"

api = HfApi(token=token)

# Ensure the repository exists
api.create_repo(
    repo_id=repo_id,
    repo_type="space",
    exist_ok=True,
    space_sdk="docker"
)

# Upload the folder
api.upload_folder(
    repo_id=repo_id,
    folder_path=".",
    repo_type="space",
)

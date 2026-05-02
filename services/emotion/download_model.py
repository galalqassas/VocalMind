import time
from funasr import AutoModel

def download_with_retry(model_name, max_retries=5, delay=5):
    for i in range(max_retries):
        try:
            print(f"Attempt {i+1}: Downloading {model_name}...")
            model = AutoModel(model=model_name, trust_remote_code=True)
            print(f"Successfully downloaded {model_name}")
            return model
        except Exception as e:
            print(f"Error downloading {model_name}: {e}")
            if i < max_retries - 1:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print(f"Failed to download {model_name} after {max_retries} attempts.")
                raise e

if __name__ == "__main__":
    download_with_retry("iic/emotion2vec_plus_base")

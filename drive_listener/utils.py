import os
import pickle
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config.settings import current_config

SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly', 'https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    """
    Authenticates and returns a Google Drive service object.
    Tries to load credentials from a token file if available,
    otherwise, uses service account credentials.
    """
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time. This is more for user-based OAuth. For service accounts,
    # GOOGLE_APPLICATION_CREDENTIALS is usually enough.

    # Using service account credentials directly
    try:
        creds_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), current_config.GOOGLE_APPLICATION_CREDENTIALS)
        if not os.path.exists(creds_path):
            raise FileNotFoundError(f"Credentials file not found at {creds_path}. "
                                    "Ensure GOOGLE_APPLICATION_CREDENTIALS is set correctly in .env "
                                    "and the file exists.")

        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"Error building Drive service: {e}")
        # Potentially log this error or raise a custom exception
        # For now, we'll let it propagate if critical, or handle downstream
        raise


def list_files_in_folder(service, folder_id, page_token=None):
    """
    Lists all files in a given Google Drive folder.
    Handles pagination.
    """
    files_list = []
    query = f"'{folder_id}' in parents and trashed = false"

    # Construct the fields string dynamically based on what's needed
    # Common fields: id, name, mimeType, createdTime, modifiedTime, webViewLink
    fields_str = "nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, webViewLink, description)"

    while True:
        try:
            response = service.files().list(
                q=query,
                spaces='drive',
                fields=fields_str,
                pageToken=page_token,
                orderBy='createdTime desc' # Process newest files first
            ).execute()

            files_list.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        except HttpError as error:
            print(f'An error occurred while listing files: {error}')
            # Depending on the error, you might want to retry or raise
            return None # Or raise a custom error
    return files_list


def download_file(service, file_id, local_path):
    """
    Downloads a file from Google Drive.
    Note: This function might need to be in a different module if it's used by OCR processor.
    For now, keeping it here if listener needs to fetch file content for some checks.
    If only metadata is needed by listener, then this might not be used directly by listener.

    Args:
        service: Authorized Google Drive service instance.
        file_id: ID of the file to download.
        local_path: Path to save the downloaded file.

    Returns:
        str: Path to the downloaded file or None if error.
    """
    try:
        request = service.files().get_media(fileId=file_id)
        # fh = io.BytesIO() # If you want to keep it in memory
        # downloader = MediaIoBaseDownload(fh, request)

        os.makedirs(os.path.dirname(local_path), exist_ok=True) # Ensure directory exists

        with open(local_path, 'wb') as fh:
            downloader = service.files().get_media(fileId=file_id)
            media_request = downloader
            # For large files, consider using MediaIoBaseDownload for chunking
            # For now, assuming files are reasonably sized
            fh.write(media_request.execute())
        print(f"File {file_id} downloaded to {local_path}")
        return local_path
    except HttpError as error:
        print(f'An error occurred while downloading file {file_id}: {error}')
        # Handle specific errors like 404 (file not found) or 403 (permission denied)
        return None
    except Exception as e:
        print(f'An unexpected error occurred during download of {file_id}: {e}')
        return None

if __name__ == '__main__':
    # Example usage (requires .env and credentials.json to be set up)
    # This part is for testing the utility functions directly.
    print("Attempting to connect to Google Drive...")
    try:
        drive_service = get_drive_service()
        if drive_service:
            print("Successfully connected to Google Drive.")
            folder_id_to_scan = current_config.DRIVE_FOLDER_ID
            if not folder_id_to_scan:
                print("DRIVE_FOLDER_ID is not set in .env. Cannot list files.")
            else:
                print(f"Listing files in folder: {folder_id_to_scan}...")
                files = list_files_in_folder(drive_service, folder_id_to_scan)
                if files is not None:
                    if not files:
                        print("No files found in the folder.")
                    else:
                        print(f"Found {len(files)} files:")
                        for item in files:
                            print(f" - {item['name']} (ID: {item['id']}, Type: {item['mimeType']})")

                        # Example: Try to download the first file if it exists
                        # if files:
                        #     first_file = files[0]
                        #     download_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp_downloads")
                        #     os.makedirs(download_dir, exist_ok=True)
                        #     file_path = os.path.join(download_dir, first_file['name'])
                        #     print(f"\nAttempting to download '{first_file['name']}' to '{file_path}'...")
                        #     downloaded_file_path = download_file(drive_service, first_file['id'], file_path)
                        #     if downloaded_file_path:
                        #         print(f"File downloaded successfully: {downloaded_file_path}")
                        #     else:
                        #         print(f"Failed to download {first_file['name']}.")
                else:
                    print("Failed to list files.")
        else:
            print("Failed to connect to Google Drive.")
    except FileNotFoundError as fnf_error:
        print(fnf_error)
    except Exception as e:
        print(f"An error occurred during the example run: {e}")

# Placeholder for a function that might be used by the main listener to get sheets service
# from googleapiclient.discovery import build as build_sheets
# def get_sheets_service():
#     creds_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), current_config.GOOGLE_APPLICATION_CREDENTIALS)
#     creds = Credentials.from_service_account_file(creds_path, scopes=['https://www.googleapis.com/auth/spreadsheets'])
#     service = build_sheets('sheets', 'v4', credentials=creds)
#     return service

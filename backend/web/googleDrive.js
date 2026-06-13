const GOOGLE_DRIVE_API_BASE = 'https://www.googleapis.com/drive/v3/files';
const UPLOAD_BASE = 'https://www.googleapis.com/upload/drive/v3/files';

function handleExpiredToken() {
  sessionStorage.removeItem('googleToken');
  window.dispatchEvent(new CustomEvent('google-token-expired'));
}

async function validateGoogleToken(accessToken) {
  try {
    const res = await fetch(`https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=${accessToken}`);
    if (!res.ok) {
      handleExpiredToken();
      return false;
    }
    return true;
  } catch (e) {
    return false;
  }
}

async function findBackupFile(accessToken) {
  const query = new URLSearchParams({
    spaces: 'appDataFolder',
    q: "name='naukri_backup.json'",
    fields: 'files(id, name, modifiedTime)',
  });
  
  const res = await fetch(`${GOOGLE_DRIVE_API_BASE}?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  
  if (!res.ok) {
    if (res.status === 401) {
      handleExpiredToken();
      throw new Error('Google Drive session expired. Please sign in again.');
    }
    throw new Error('Failed to search Google Drive');
  }
  
  const data = await res.json();
  return data.files && data.files.length > 0 ? data.files[0] : null;
}

async function uploadBackup(accessToken, backupData) {
  const existingFile = await findBackupFile(accessToken);
  
  const metadata = {
    name: 'naukri_backup.json',
  };
  
  let url = `${UPLOAD_BASE}?uploadType=multipart`;
  let method = 'POST';
  
  if (existingFile) {
    url = `${UPLOAD_BASE}/${existingFile.id}?uploadType=multipart`;
    method = 'PATCH';
  } else {
    metadata.parents = ['appDataFolder'];
  }
  
  const fileContent = JSON.stringify(backupData);
  
  const formData = new FormData();
  formData.append('metadata', new Blob([JSON.stringify(metadata)], { type: 'application/json' }));
  formData.append('file', new Blob([fileContent], { type: 'application/json' }));

  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    body: formData,
  });
  
  if (!res.ok) {
    if (res.status === 401) {
      handleExpiredToken();
      throw new Error('Google Drive session expired. Please sign in again.');
    }
    const errorText = await res.text();
    console.error('Upload Error:', errorText);
    throw new Error('Failed to upload backup to Google Drive');
  }
}

async function downloadBackup(accessToken) {
  const file = await findBackupFile(accessToken);
  if (!file) return null;
  
  const res = await fetch(`${GOOGLE_DRIVE_API_BASE}/${file.id}?alt=media`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  
  if (!res.ok) {
    if (res.status === 401) {
      handleExpiredToken();
      throw new Error('Google Drive session expired. Please sign in again.');
    }
    throw new Error('Failed to download backup from Google Drive');
  }
  
  return await res.json();
}

async function deleteBackup(accessToken) {
  const file = await findBackupFile(accessToken);
  if (!file) return;
  
  const res = await fetch(`${GOOGLE_DRIVE_API_BASE}/${file.id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  
  if (!res.ok) {
    if (res.status === 401) {
      handleExpiredToken();
      throw new Error('Google Drive session expired. Please sign in again.');
    }
    throw new Error('Failed to delete backup from Google Drive');
  }
}

window.googleDrive = {
  validateGoogleToken,
  findBackupFile,
  uploadBackup,
  downloadBackup,
  deleteBackup
};

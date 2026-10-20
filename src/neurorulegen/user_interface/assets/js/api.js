export async function request(url, options = {}) {
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
    if (!response.ok) throw new Error(`Request failed (${response.status}). Please try again.`);
    return await response.json();
  } catch (error) {
    window.alert(error.message || 'The server could not be reached. Please try again.');
    return null;
  }
}

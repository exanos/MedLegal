// static/app.js

document.getElementById('upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();

  const fileInput = document.getElementById('pdf-upload');
  const claimInput = document.getElementById('claim-id');
  const processingDiv = document.getElementById('processing-overlay');
  const outputDiv = document.getElementById('pdf-output');
  const containerDiv = document.getElementById('container');

  if (fileInput.files.length === 0) {
    alert('Please select a PDF file to upload.');
    return;
  }

  const formData = new FormData();
  formData.append('pdf', fileInput.files[0]);
  if (claimInput.value.trim()) formData.append('claim_id', claimInput.value.trim());

  // Show overlay
  containerDiv.style.display = 'none';
  processingDiv.style.setProperty('display', 'flex', 'important');
  outputDiv.innerHTML = '';

  try {
    const resp = await fetch('/upload', { method: 'POST', body: formData });

    if (!resp.ok) {
      let msg = 'Error processing the claim.';
      try {
        const j = await resp.json();
        if (j && j.error) msg = j.error;
      } catch {}
      alert(msg);
      return;
    }

    // We return HTML from the server (Markdown converted to HTML)
    const html = await resp.text();
    outputDiv.innerHTML = html;

    // Scroll to the report
    outputDiv.scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    console.error(err);
    alert('An error occurred during upload.');
  } finally {
    // Hide overlay and show form again for next upload
    processingDiv.style.setProperty('display', 'none', 'important');
    containerDiv.style.display = 'block';
    fileInput.value = '';
  }
});

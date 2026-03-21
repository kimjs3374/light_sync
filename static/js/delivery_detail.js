function openContactEdit(id, category, name, phone, email) {
    document.getElementById('edit_contact_id').value = id || '';
    document.getElementById('edit_contact_category').value = category || '';
    document.getElementById('edit_contact_name').value = name || '';
    document.getElementById('edit_contact_phone').value = phone || '';
    document.getElementById('edit_contact_email').value = email || '';
    new bootstrap.Modal(document.getElementById('editContactModal')).show();
}
function openContactEditFromBtn(btn) {
    openContactEdit(btn.dataset.id, btn.dataset.category, btn.dataset.name, btn.dataset.phone, btn.dataset.email);
}

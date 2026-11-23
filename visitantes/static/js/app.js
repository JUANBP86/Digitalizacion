"use strict";

const requiredVisitorFields = ["nombre", "empresa", "arl", "eps", "telefono"];
const entryForm = document.getElementById("entryForm");
const visitorStatus = document.getElementById("visitorStatus");
const signatureCanvas = document.getElementById("signatureCanvas");
const signatureContext = signatureCanvas.getContext("2d");
let visitorLookupTimer;
let lookupRequestNumber = 0;
let signatureDrawn = false;
let signatureInProgress = false;

async function api(url, options = {}) {
    let response;
    try {
        response = await fetch(url, {
            headers: { "Content-Type": "application/json" },
            ...options,
        });
    } catch {
        throw new Error("No se pudo conectar con el servidor. Verifique la red e intente de nuevo.");
    }

    let result;
    try {
        result = await response.json();
    } catch {
        throw new Error("El servidor devolvió una respuesta no válida.");
    }
    if (!response.ok) {
        throw new Error(result.error || "No fue posible completar la solicitud.");
    }
    return result;
}

function setMessage(element, message = "", type = "") {
    element.textContent = message;
    element.className = `inline-message ${type}`.trim();
}

function createEquipmentRow() {
    const row = document.createElement("tr");
    for (const field of ["marca", "referencia", "serie"]) {
        const cell = document.createElement("td");
        const input = document.createElement("input");
        input.type = "text";
        input.dataset.field = field;
        input.setAttribute("aria-label", field === "serie" ? "Número de serie" : field);
        input.placeholder = field === "serie" ? "N.º de serie" : field[0].toUpperCase() + field.slice(1);
        cell.append(input);
        row.append(cell);
    }
    const actionCell = document.createElement("td");
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "remove-equipment";
    removeButton.setAttribute("aria-label", "Eliminar equipo");
    removeButton.textContent = "×";
    removeButton.addEventListener("click", () => {
        row.remove();
        updateEquipmentEmptyState();
    });
    actionCell.append(removeButton);
    row.append(actionCell);
    return row;
}

function updateEquipmentEmptyState() {
    document.getElementById("emptyEquipment").hidden =
        document.getElementById("equipmentRows").children.length > 0;
}

function clearVisitorFields() {
    for (const field of requiredVisitorFields) {
        document.getElementById(field).value = "";
    }
    document.getElementById("categoria").value = "";
    document.getElementById("personaVisita").value = "";
    document.getElementById("autorizacionDatos").checked = false;
    clearSignature();
}

function clearSignature() {
    signatureContext.fillStyle = "#ffffff";
    signatureContext.fillRect(0, 0, signatureCanvas.width, signatureCanvas.height);
    signatureContext.beginPath();
    signatureDrawn = false;
}

function signaturePosition(event) {
    const bounds = signatureCanvas.getBoundingClientRect();
    return {
        x: (event.clientX - bounds.left) * signatureCanvas.width / bounds.width,
        y: (event.clientY - bounds.top) * signatureCanvas.height / bounds.height,
    };
}

function startSignature(event) {
    event.preventDefault();
    signatureInProgress = true;
    signatureCanvas.setPointerCapture(event.pointerId);
    const point = signaturePosition(event);
    signatureDrawn = true;
    signatureContext.beginPath();
    signatureContext.moveTo(point.x, point.y);
}

function drawSignature(event) {
    if (!signatureInProgress) return;
    event.preventDefault();
    const point = signaturePosition(event);
    signatureContext.lineWidth = 2.5;
    signatureContext.lineCap = "round";
    signatureContext.lineJoin = "round";
    signatureContext.strokeStyle = "#23364a";
    signatureContext.lineTo(point.x, point.y);
    signatureContext.stroke();
}

function finishSignature() {
    signatureInProgress = false;
    signatureContext.beginPath();
}

function clearEquipmentRows() {
    document.getElementById("equipmentRows").replaceChildren();
    updateEquipmentEmptyState();
}

async function lookupVisitor() {
    const cedula = document.getElementById("cedula").value.trim();
    const requestNumber = ++lookupRequestNumber;
    clearTimeout(visitorLookupTimer);
    setMessage(visitorStatus);
    entryForm.hidden = true;
    clearVisitorFields();
    clearEquipmentRows();

    if (!cedula) return;

    setMessage(visitorStatus, "Consultando sus datos…", "info");
    visitorLookupTimer = window.setTimeout(async () => {
        try {
            const result = await api(`/api/visitantes/${encodeURIComponent(cedula)}`);
            if (requestNumber !== lookupRequestNumber) return;
            if (result.found) {
                if (result.visitante.categoria) {
                    document.getElementById("categoria").value = result.visitante.categoria;
                }
                for (const field of requiredVisitorFields) {
                    document.getElementById(field).value = result.visitante[field] || "";
                }
                setMessage(visitorStatus, "Encontramos su registro. Verifique sus datos y complete la persona que visita.", "success");
            } else {
                setMessage(visitorStatus, "Primera visita. Complete sus datos para continuar.", "info");
            }
            entryForm.hidden = false;
        } catch (error) {
            if (requestNumber !== lookupRequestNumber) return;
            setMessage(visitorStatus, error.message, "error");
        }
    }, 300);
}

function collectEquipment() {
    return [...document.querySelectorAll("#equipmentRows tr")]
        .map((row) => Object.fromEntries(
            [...row.querySelectorAll("input[data-field]")].map((input) => [
                input.dataset.field,
                input.value.trim(),
            ]),
        ))
        .filter((item) => Object.values(item).some(Boolean));
}

async function submitEntry(event) {
    event.preventDefault();
    const message = document.getElementById("entryMessage");
    const submitButton = document.getElementById("submitEntry");
    const cedula = document.getElementById("cedula").value.trim();

    if (!cedula) {
        message.textContent = "Ingrese el número de cédula o documento.";
        message.className = "form-message error";
        document.getElementById("cedula").focus();
        return;
    }
    if (!entryForm.reportValidity()) return;
    if (!signatureDrawn) {
        message.textContent = "Dibuje su firma antes de registrar el ingreso.";
        message.className = "form-message error";
        signatureCanvas.focus();
        return;
    }

    submitButton.disabled = true;
    message.textContent = "";
    const payload = {
        cedula,
        categoria: document.getElementById("categoria").value,
        nombre: document.getElementById("nombre").value.trim(),
        empresa: document.getElementById("empresa").value.trim(),
        arl: document.getElementById("arl").value.trim(),
        eps: document.getElementById("eps").value.trim(),
        telefono: document.getElementById("telefono").value.trim(),
        persona_visita: document.getElementById("personaVisita").value.trim(),
        equipos: collectEquipment(),
        autorizacion_datos: document.getElementById("autorizacionDatos").checked,
        acuerdo_confidencialidad: document.getElementById("acuerdoConfidencialidad").checked,
        firma: signatureCanvas.toDataURL("image/png"),
    };

    try {
        const result = await api("/api/ingresos", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content,
            },
            body: JSON.stringify(payload),
        });
        message.textContent = `${result.message} Puede dirigirse a recepción.`;
        message.className = "form-message success";
        entryForm.reset();
        document.getElementById("cedula").value = "";
        entryForm.hidden = true;
        clearSignature();
        clearEquipmentRows();
        setMessage(visitorStatus, "Registro completado.", "success");
        lookupRequestNumber += 1;
    } catch (error) {
        message.textContent = error.message;
        message.className = "form-message error";
    } finally {
        submitButton.disabled = false;
    }
}

const cedulaInput = document.getElementById("cedula");
cedulaInput.addEventListener("input", () => {
    cedulaInput.value = cedulaInput.value.replace(/\D/g, "");
    lookupVisitor();
});
entryForm.addEventListener("submit", submitEntry);
signatureCanvas.addEventListener("pointerdown", startSignature);
signatureCanvas.addEventListener("pointermove", drawSignature);
signatureCanvas.addEventListener("pointerup", finishSignature);
signatureCanvas.addEventListener("pointercancel", finishSignature);
document.getElementById("clearSignature").addEventListener("click", clearSignature);
document.getElementById("addEquipment").addEventListener("click", () => {
    document.getElementById("equipmentRows").append(createEquipmentRow());
    updateEquipmentEmptyState();
});

clearSignature();

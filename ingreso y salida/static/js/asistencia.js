"use strict";

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const lookupForm = document.getElementById("lookupForm");
const departureForm = document.getElementById("departureForm");
const documentInput = document.getElementById("documento");
const employeePanel = document.getElementById("employeePanel");
const currentMovement = document.getElementById("currentMovement");
const messageElement = document.getElementById("attendanceMessage");
const signatureCanvas = document.getElementById("signatureCanvas");
const signatureContext = signatureCanvas.getContext("2d");
let employeeDocument = "";
let signatureDrawn = false;

signatureContext.lineWidth = 3;
signatureContext.lineCap = "round";
signatureContext.lineJoin = "round";

signatureCanvas.addEventListener("pointerdown", (event) => {
    const bounds = signatureCanvas.getBoundingClientRect();
    signatureCanvas.setPointerCapture(event.pointerId);
    signatureContext.beginPath();
    signatureContext.moveTo(
        (event.clientX - bounds.left) * signatureCanvas.width / bounds.width,
        (event.clientY - bounds.top) * signatureCanvas.height / bounds.height,
    );
    signatureDrawn = true;
});

signatureCanvas.addEventListener("pointermove", (event) => {
    if (!signatureCanvas.hasPointerCapture(event.pointerId)) return;
    const bounds = signatureCanvas.getBoundingClientRect();
    signatureContext.lineTo(
        (event.clientX - bounds.left) * signatureCanvas.width / bounds.width,
        (event.clientY - bounds.top) * signatureCanvas.height / bounds.height,
    );
    signatureContext.stroke();
});

function clearSignature() {
    signatureContext.clearRect(0, 0, signatureCanvas.width, signatureCanvas.height);
    signatureDrawn = false;
}

document.getElementById("clearSignature").addEventListener("click", clearSignature);

function showMessage(text = "", kind = "") {
    messageElement.textContent = text;
    messageElement.className = `form-message ${kind}`.trim();
}

function renderEmployee(employee, state) {
    employeeDocument = employee.documento;
    document.getElementById("employeeName").textContent = employee.nombre;
    document.getElementById("employeeDetails").textContent = employee.area;
    const activeExit = state === "fuera";
    const declaredNoReturn = state === "no_regresa";

    currentMovement.hidden = !activeExit && !declaredNoReturn;
    departureForm.hidden = activeExit || declaredNoReturn;
    if (activeExit || declaredNoReturn) {
        document.getElementById("movementStatus").textContent = activeExit
            ? `Salida registrada: ${new Date(employee.salida).toLocaleString("es-CO")}`
            : `Salida registrada sin regreso previsto: ${new Date(employee.salida).toLocaleString("es-CO")}`;
        document.getElementById("movementDetails").textContent =
            `Motivo: ${employee.motivo} · Destino: ${employee.destino}`;
        document.getElementById("returnButton").hidden = false;
    }
    employeePanel.hidden = false;
}

async function postJson(url, payload) {
    let response;
    try {
        response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": csrfToken,
            },
            body: JSON.stringify(payload),
        });
    } catch {
        throw new Error("No se pudo conectar con el servidor. Verifique la red.");
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "No fue posible completar la solicitud.");
    return result;
}

async function lookupEmployee() {
    const result = await postJson("/api/salidas/consultar", {
        documento: employeeDocument,
    });
    renderEmployee(result.empleado, result.estado);
}

lookupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    showMessage();
    employeePanel.hidden = true;
    employeeDocument = documentInput.value.trim();
    try {
        await lookupEmployee();
    } catch (error) {
        showMessage(error.message, "error");
    }
});

departureForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const returnChoice = departureForm.querySelector('input[name="no_regresa"]:checked');
    if (!returnChoice) {
        showMessage("Indique si regresará a las instalaciones durante este turno.", "error");
        return;
    }
    if (!signatureDrawn) {
        showMessage("Dibuje su firma antes de registrar la salida.", "error");
        return;
    }
    const button = departureForm.querySelector('button[type="submit"]');
    let reloadPending = false;
    button.disabled = true;
    showMessage();
    try {
        const result = await postJson("/api/salidas/registrar", {
            documento: employeeDocument,
            motivo: document.getElementById("motivo").value.trim(),
            destino: document.getElementById("destino").value.trim(),
            firma: signatureCanvas.toDataURL("image/png"),
            no_regresa: returnChoice.value === "true",
        });
        showMessage(result.message, "success");
        departureForm.reset();
        clearSignature();
        employeePanel.hidden = true;
        documentInput.value = "";
        documentInput.focus();
        lookupForm.querySelector('button[type="submit"]').disabled = true;
        reloadPending = true;
        window.setTimeout(() => window.location.reload(), 1800);
    } catch (error) {
        showMessage(error.message, "error");
    } finally {
        if (!reloadPending) button.disabled = false;
    }
});

document.getElementById("returnButton").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    showMessage();
    try {
        const result = await postJson("/api/salidas/regreso", {
            documento: employeeDocument,
        });
        showMessage(result.message, "success");
        employeePanel.hidden = true;
        documentInput.value = "";
        documentInput.focus();
        lookupForm.querySelector('button[type="submit"]').disabled = true;
        window.setTimeout(() => window.location.reload(), 1800);
    } catch (error) {
        showMessage(error.message, "error");
        button.disabled = false;
    }
});

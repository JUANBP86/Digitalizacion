"use strict";

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const isAdmin = document.body.dataset.role === "admin";
const views = Object.fromEntries(Object.entries({
    accesos: document.getElementById("view-accesos"),
    empleados: document.getElementById("view-empleados"),
    cuentas: document.getElementById("view-cuentas"),
    historial: document.getElementById("view-historial"),
}).filter(([, section]) => section));
let history = [];
let selectedMovementId = null;

async function api(url, options = {}) {
    let response;
    try {
        response = await fetch(url, {
            ...options,
            headers: {
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                ...(options.method ? { "X-CSRF-Token": csrfToken } : {}),
                ...options.headers,
            },
        });
    } catch {
        throw new Error("No se pudo conectar con el servidor. Verifique la red.");
    }
    const result = await response.json();
    if (response.status === 401) {
        window.location.assign("/admin/login");
        throw new Error("La sesión expiró.");
    }
    if (!response.ok) throw new Error(result.error || "No fue posible completar la solicitud.");
    return result;
}

function message(id, text = "", kind = "") {
    const element = document.getElementById(id);
    element.textContent = text;
    element.className = `form-message ${kind}`.trim();
}

function cell(row, value) {
    const element = document.createElement("td");
    element.textContent = value ?? "";
    row.append(element);
}

function displayDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString("es-CO");
}

function dateOnly(value) {
    if (!value) return "";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "";
    const year = parsed.getFullYear();
    const month = String(parsed.getMonth() + 1).padStart(2, "0");
    const day = String(parsed.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function displayTime(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
        ? value
        : parsed.toLocaleTimeString("es-CO", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
}

function displayDateTime(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
        ? value
        : parsed.toLocaleString("es-CO", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
}

function showView(name) {
    for (const [key, section] of Object.entries(views)) {
        section.hidden = key !== name;
        section.classList.toggle("is-visible", key === name);
    }
    document.querySelectorAll(".nav-link").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.view === name);
    });
    if (name === "accesos") loadActive();
    if (name === "empleados") loadEmployees();
    if (name === "historial") loadHistory();
}

async function loadActive() {
    message("activeMessage");
    try {
        const { activos } = await api("/api/activos");
        const list = document.getElementById("activeList");
        list.replaceChildren();
        document.getElementById("activeCount").textContent = String(activos.length);
        document.getElementById("activeNavCount").textContent = String(activos.length);
        document.getElementById("activeEmpty").hidden = activos.length !== 0;
        for (const person of activos) {
            const card = document.createElement("article");
            card.className = "person-card";
            const detail = document.createElement("div");
            const name = document.createElement("h3");
            name.textContent = person.nombre;
            const meta = document.createElement("p");
            meta.textContent = `${person.area} · ${person.cargo} · Documento ${person.documento}`;
            const time = document.createElement("p");
            time.className = "muted";
            time.textContent = `Salida: ${displayDate(person.salida)}`;
            const reason = document.createElement("p");
            reason.textContent = `Motivo: ${person.motivo} · Destino: ${person.destino}`;
            detail.append(name, meta, time, reason);
            card.append(detail);
            if (isAdmin) {
                const actions = document.createElement("div");
                actions.className = "person-card-actions";
                const regularizeButton = document.createElement("button");
                regularizeButton.className = "button button-secondary";
                regularizeButton.type = "button";
                regularizeButton.dataset.movementId = String(person.movimiento_id);
                regularizeButton.textContent = "Regularizar regreso";
                actions.append(regularizeButton);
                card.append(actions);
            }
            list.append(card);
        }
    } catch (error) {
        message("activeMessage", error.message, "error");
    }
}

async function loadEmployees() {
    try {
        const { empleados } = await api("/api/empleados");
        const body = document.getElementById("employeeRows");
        body.replaceChildren();
        document.getElementById("employeeEmpty").hidden = empleados.length !== 0;
        for (const employee of empleados) {
            const row = document.createElement("tr");
            cell(row, employee.documento);
            cell(row, employee.nombre);
            cell(row, employee.area);
            cell(row, employee.cargo);
            cell(row, employee.activo ? "Activo" : "Inactivo");
            body.append(row);
        }
    } catch (error) {
        message("employeeMessage", error.message, "error");
    }
}

async function loadHistory() {
    message("historyMessage");
    try {
        const result = await api("/api/historial");
        history = result.registros;
        renderHistory();
    } catch (error) {
        message("historyMessage", error.message, "error");
    }
}

function renderHistory() {
    const query = document.getElementById("historySearch").value.trim().toLocaleLowerCase("es");
    const filtered = history.filter((record) =>
        [
            record.documento, record.nombre, record.area, record.cargo,
            record.motivo, record.destino, record.estado,
            record.salida, record.regreso, record.regreso_regularizado_por,
            record.regreso_regularizado_motivo, record.regreso_regularizado_evidencia,
        ].join(" ").toLocaleLowerCase("es").includes(query));
    const body = document.getElementById("historyRows");
    body.replaceChildren();
    for (const [index, record] of filtered.entries()) {
        const row = document.createElement("tr");
        cell(row, String(index + 1));
        cell(row, dateOnly(record.salida).split("-").reverse().join("/"));
        cell(row, record.nombre);
        cell(row, record.documento);
        cell(row, record.cargo);
        cell(row, displayTime(record.salida));
        const returnTime = !record.regreso
            ? "—"
            : record.regreso_regularizado && !record.regreso_confirmado
                ? `Cierre administrativo (hora no confirmada): ${displayDateTime(record.regreso)}`
                : record.regreso_regularizado
                    ? `Hora confirmada mediante regularización: ${displayDateTime(record.regreso)}`
                    : displayDateTime(record.regreso);
        cell(row, returnTime);
        const auditDetails = record.regreso_regularizado
            ? [
                `Por: ${record.regreso_regularizado_por || "—"}`,
                `El: ${displayDateTime(record.regreso_regularizado_en)}`,
                `Motivo: ${record.regreso_regularizado_motivo || "—"}`,
                record.regreso_regularizado_evidencia
                    ? `Evidencia: ${record.regreso_regularizado_evidencia}`
                    : "",
            ].filter(Boolean).join(" · ")
            : "—";
        cell(row, auditDetails);
        const signatureCell = document.createElement("td");
        if (record.tiene_firma) {
            const signature = document.createElement("img");
            signature.className = "signature-thumbnail";
            signature.alt = "Firma registrada";
            signature.src = `/api/salidas/${record.movimiento_id}/firma`;
            signatureCell.append(signature);
        } else {
            signatureCell.textContent = "—";
        }
        row.append(signatureCell);
        cell(row, record.motivo);
        cell(row, record.destino);
        cell(row, record.estado);
        body.append(row);
    }
    document.getElementById("historyEmpty").hidden = history.length !== 0;
    document.getElementById("historyNoMatches").hidden =
        history.length === 0 || filtered.length !== 0;
}

document.querySelectorAll(".nav-link").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
});
document.getElementById("refreshActive").addEventListener("click", loadActive);
document.getElementById("refreshHistory").addEventListener("click", loadHistory);
document.getElementById("historySearch").addEventListener("input", renderHistory);
const regularizeDialog = document.getElementById("regularizeDialog");
const regularizeForm = document.getElementById("regularizeForm");
const realReturnTime = document.getElementById("realReturnTime");
const regularizeEvidence = document.getElementById("regularizeEvidence");
if (isAdmin) {
    document.getElementById("activeList").addEventListener("click", (event) => {
        const button = event.target.closest("button[data-movement-id]");
        if (!button) return;
        selectedMovementId = button.dataset.movementId;
        regularizeForm.reset();
        regularizeEvidence.required = false;
        message("regularizeMessage");
        const card = button.closest(".person-card");
        document.getElementById("regularizeEmployee").textContent =
            `${card.querySelector("h3").textContent} · ${card.querySelector(".muted").textContent}`;
        regularizeDialog.showModal();
    });
    document.getElementById("cancelRegularize").addEventListener("click", () => {
        regularizeDialog.close();
    });
    realReturnTime.addEventListener("input", () => {
        regularizeEvidence.required = Boolean(realReturnTime.value);
    });
    regularizeForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const parsedReturn = realReturnTime.value ? new Date(realReturnTime.value) : null;
        if (parsedReturn && Number.isNaN(parsedReturn.getTime())) {
            message("regularizeMessage", "La hora real del regreso no es válida.", "error");
            return;
        }
        const data = {
            hora_real: parsedReturn ? parsedReturn.toISOString() : "",
            motivo: document.getElementById("regularizeReason").value.trim(),
            evidencia: regularizeEvidence.value.trim(),
        };
        const button = regularizeForm.querySelector('button[type="submit"]');
        button.disabled = true;
        message("regularizeMessage");
        try {
            const result = await api(`/api/salidas/${selectedMovementId}/regularizar`, {
                method: "POST",
                body: JSON.stringify(data),
            });
            regularizeDialog.close();
            regularizeForm.reset();
            selectedMovementId = null;
            await loadActive();
            message("activeMessage", result.message, "success");
            await loadHistory();
        } catch (error) {
            message("regularizeMessage", error.message, "error");
        } finally {
            button.disabled = false;
        }
    });
    document.getElementById("viewerAccountForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const data = Object.fromEntries(new FormData(form).entries());
        try {
            const result = await api("/api/usuarios/lectura", {
                method: "POST",
                body: JSON.stringify(data),
            });
            form.reset();
            message("viewerAccountMessage", result.message, "success");
        } catch (error) {
            message("viewerAccountMessage", error.message, "error");
        }
    });
}
const reportDate = document.getElementById("reportDate");
const now = new Date();
reportDate.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;

document.getElementById("employeeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    try {
        const result = await api("/api/empleados", {
            method: "POST",
            body: JSON.stringify(data),
        });
        form.reset();
        message("employeeMessage", result.message, "success");
        await loadEmployees();
    } catch (error) {
        message("employeeMessage", error.message, "error");
    }
});

showView(isAdmin ? "accesos" : "historial");

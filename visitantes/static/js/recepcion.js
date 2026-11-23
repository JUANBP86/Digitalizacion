"use strict";

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const views = {
    activos: document.getElementById("view-activos"),
    historial: document.getElementById("view-historial"),
    politica: document.getElementById("view-politica"),
};
const historySearch = document.getElementById("historySearch");
let allHistory = [];

async function api(url, options = {}) {
    let response;
    try {
        response = await fetch(url, {
            headers: {
                "Content-Type": "application/json",
                ...(options.method ? { "X-CSRF-Token": csrfToken } : {}),
                ...options.headers,
            },
            ...options,
        });
    } catch {
        throw new Error("No se pudo conectar con el servidor. Verifique la red e intente de nuevo.");
    }
    const result = await response.json();
    if (response.status === 401) {
        window.location.assign("/recepcion/login");
        throw new Error("La sesión de recepción expiró.");
    }
    if (!response.ok) {
        throw new Error(result.error || "No fue posible completar la solicitud.");
    }
    return result;
}

function setMessage(element, message = "", type = "") {
    element.textContent = message;
    element.className = `form-message ${type}`.trim();
}

function textElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text || "";
    return element;
}

function formatEquipment(equipment) {
    if (!equipment || (Array.isArray(equipment) && equipment.length === 0)) {
        return "Ninguno";
    }
    if (typeof equipment === "string") return equipment;
    if (!Array.isArray(equipment)) return "Ninguno";
    return equipment.map((item) => {
        if (typeof item !== "object" || item === null) return "";
        return `Marca: ${item.marca || ""} | Referencia: ${item.referencia || ""} | Serie: ${item.serie || ""}`;
    }).filter(Boolean).join("\n") || "Ninguno";
}

function renderActiveVisitors(visitors) {
    const container = document.getElementById("activeList");
    container.replaceChildren();
    document.getElementById("activeCount").textContent = String(visitors.length);
    document.getElementById("activeNavCount").textContent = String(visitors.length);
    document.getElementById("activeEmpty").hidden = visitors.length > 0;

    for (const visitor of visitors) {
        const card = document.createElement("article");
        card.className = "visitor-card";
        const identity = document.createElement("div");
        identity.append(
            textElement("h3", "visitor-name", visitor.nombre),
            textElement("p", "visitor-company", visitor.empresa),
        );
        const details = document.createElement("div");
        details.className = "visitor-detail";
        details.append(
            textElement("span", "", `Documento: ${visitor.cedula}`),
            textElement("span", "", `Categoría: ${visitor.categoria || "No especificada"}`),
            textElement("span", "", `Visita a: ${visitor.persona_visita}`),
            textElement("span", "", `Ingreso: ${visitor.fecha} ${visitor.hora_ingreso}`),
        );
        const equipment = textElement("div", "visitor-equipment", formatEquipment(visitor.equipos));
        const actions = document.createElement("div");
        actions.style.display = "flex";
        actions.style.gap = "0.5rem";
        actions.style.flexWrap = "wrap";
        actions.style.alignItems = "center";

        const docLink = document.createElement("a");
        docLink.className = "button button-secondary";
        docLink.href = `/api/ingresos/${visitor.id}/acuerdo-pdf`;
        docLink.target = "_blank";
        docLink.rel = "noopener";
        docLink.textContent = "Acuerdo PDF";

        const exitButton = textElement("button", "button button-exit", "Registrar salida");
        exitButton.type = "button";
        exitButton.addEventListener("click", () => registerExit(visitor.id, exitButton));

        actions.append(docLink, exitButton);
        card.append(identity, details, equipment, actions);
        container.append(card);
    }
}

async function loadActiveVisitors() {
    const message = document.getElementById("activeMessage");
    setMessage(message);
    try {
        const result = await api("/api/activos");
        renderActiveVisitors(result.visitantes);
    } catch (error) {
        setMessage(message, error.message, "error");
    }
}

async function registerExit(id, button) {
    const message = document.getElementById("activeMessage");
    button.disabled = true;
    try {
        await api(`/api/ingresos/${id}/salida`, { method: "POST", body: "{}" });
        setMessage(message, "Salida registrada correctamente.", "success");
        await loadActiveVisitors();
    } catch (error) {
        button.disabled = false;
        setMessage(message, error.message, "error");
    }
}

function renderHistory(registros) {
    const body = document.getElementById("historyRows");
    const empty = document.getElementById("historyEmpty");
    const noMatches = document.getElementById("historyNoMatches");
    const query = historySearch.value.trim().toLocaleLowerCase("es");
    const filtered = registros.filter((item) => [
        item.nombre, item.cedula, item.categoria, item.empresa, item.persona_visita,
        item.arl, item.eps, item.telefono, formatEquipment(item.equipos),
    ].join(" ").toLocaleLowerCase("es").includes(query));

    body.replaceChildren();
    empty.hidden = registros.length !== 0;
    noMatches.hidden = registros.length === 0 || filtered.length !== 0;
    for (const record of filtered) {
        const row = document.createElement("tr");
        const statusCell = document.createElement("td");
        statusCell.append(textElement(
            "span",
            `status-badge${record.estado === "SALIÓ" ? " exited" : ""}`,
            record.estado,
        ));
        row.append(statusCell);
        for (const value of [
            `${record.fecha} ${record.hora_ingreso}`,
            record.hora_salida || "—",
            record.nombre,
            record.cedula,
            record.categoria || "No especificada",
            record.empresa,
            record.persona_visita,
            `${record.arl} / ${record.eps}`,
            record.telefono,
            formatEquipment(record.equipos),
        ]) {
            row.append(textElement("td", "", value));
        }
        row.append(textElement(
            "td",
            "",
            record.autorizacion_datos ? "Autorizó" : "No disponible",
        ));

        const acuerdoCell = document.createElement("td");
        const acuerdoLink = document.createElement("a");
        acuerdoLink.href = `/api/ingresos/${record.id}/acuerdo-pdf`;
        acuerdoLink.target = "_blank";
        acuerdoLink.rel = "noopener";
        acuerdoLink.textContent = "Descargar PDF";
        acuerdoLink.className = "button button-secondary";
        acuerdoLink.style.padding = "0.25rem 0.5rem";
        acuerdoLink.style.fontSize = "0.8rem";
        acuerdoCell.append(acuerdoLink);
        row.append(acuerdoCell);

        const signatureCell = document.createElement("td");
        if (record.tiene_firma) {
            const signatureLink = document.createElement("a");
            signatureLink.href = `/api/ingresos/${record.id}/firma`;
            signatureLink.target = "_blank";
            signatureLink.rel = "noopener";
            signatureLink.textContent = "Ver firma";
            signatureCell.append(signatureLink);
        } else {
            signatureCell.textContent = "No disponible";
        }
        row.append(signatureCell);
        body.append(row);
    }
}

async function loadHistory() {
    const message = document.getElementById("historyMessage");
    setMessage(message);
    try {
        const result = await api("/api/historial");
        allHistory = result.registros;
        document.getElementById("historyTotal").textContent = String(allHistory.length);
        document.getElementById("historyActive").textContent = String(
            allHistory.filter((item) => item.estado === "ACTIVO").length,
        );
        document.getElementById("historyExited").textContent = String(
            allHistory.filter((item) => item.estado === "SALIÓ").length,
        );
        renderHistory(allHistory);
    } catch (error) {
        setMessage(message, error.message, "error");
    }
}

function showView(name) {
    for (const [viewName, element] of Object.entries(views)) {
        const active = viewName === name;
        element.hidden = !active;
        element.classList.toggle("is-visible", active);
    }
    for (const button of document.querySelectorAll(".nav-link")) {
        button.classList.toggle("is-active", button.dataset.view === name);
    }
    if (name === "activos") loadActiveVisitors();
    if (name === "historial") loadHistory();
}

for (const button of document.querySelectorAll(".nav-link")) {
    button.addEventListener("click", () => showView(button.dataset.view));
}
document.getElementById("refreshActive").addEventListener("click", loadActiveVisitors);
document.getElementById("refreshHistory").addEventListener("click", loadHistory);
historySearch.addEventListener("input", () => renderHistory(allHistory));

const policyUploadForm = document.getElementById("policyUploadForm");
policyUploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.getElementById("policyMessage");
    const button = document.getElementById("uploadPolicy");
    button.disabled = true;
    setMessage(message);

    try {
        let response;
        try {
            response = await fetch(policyUploadForm.action, {
                method: "POST",
                headers: { "X-CSRF-Token": csrfToken },
                body: new FormData(policyUploadForm),
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
        if (response.status === 401) {
            window.location.assign("/recepcion/login");
            throw new Error("La sesión de recepción expiró.");
        }
        if (!response.ok) {
            throw new Error(result.error || "No fue posible cargar el documento.");
        }

        setMessage(message, result.message, "success");
        document.getElementById("policyStatus").textContent =
            "Hay una política cargada. Si sube otro PDF, reemplazará el documento actual.";
        policyUploadForm.reset();
    } catch (error) {
        setMessage(message, error.message, "error");
    } finally {
        button.disabled = false;
    }
});

loadActiveVisitors();
window.setInterval(() => {
    if (!views.activos.hidden) loadActiveVisitors();
}, 30000);

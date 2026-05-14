document.addEventListener("DOMContentLoaded", () => {
    const langPicker = document.getElementById("langPicker");
    const dateStrip = document.getElementById("dateStrip");
    const newsGrid = document.getElementById("newsGrid");
    const moreBtn = document.getElementById("moreBtn");

    let state = {
        lang: "ru",
        date: "latest", // 🔥 По умолчанию "Последние новости"
        offset: 0,
        limit: 10
    };

    // 🔹 Генерация кнопок
    function renderDateButtons() {
        dateStrip.innerHTML = "";
        const today = new Date();

        createBtn("🔥 Последние", "latest", true);

        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        createBtn("Вчера", formatDate(yesterday), false);

        for (let i = 2; i <= 6; i++) {
            const d = new Date(today);
            d.setDate(d.getDate() - i);
            createBtn(
                d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }),
                formatDate(d),
                false
            );
        }

        function createBtn(text, dateVal, isActive) {
            const btn = document.createElement("button");
            btn.className = `date-btn ${isActive ? "active" : ""}`;
            btn.dataset.date = dateVal;
            btn.textContent = text;
            dateStrip.appendChild(btn);
        }
    }

    function formatDate(date) {
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    }

    // 🔹 Загрузка новостей
    async function fetchNews(reset = true) {
        if (reset) {
            state.offset = 0;
            newsGrid.innerHTML = `<div class="loader">⏳ Загрузка...</div>`;
            moreBtn.classList.add("hidden");
        }

        // 🔥 Если "latest", не передаём параметр date в API
        let url = `/api/news?lang=${state.lang}&offset=${state.offset}&limit=${state.limit}`;
        if (state.date !== "latest") {
            url += `&date=${state.date}`;
        }

        try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`Сервер вернул ${res.status}`);
            const data = await res.json();

            if (reset) newsGrid.innerHTML = "";

            if (data.length === 0) {
                newsGrid.innerHTML += `<div class="loader">📭 Новостей пока нет. Нажми 🔄 Обновить.</div>`;
                moreBtn.classList.add("hidden");
                return;
            }

            data.forEach(n => {
                const card = document.createElement("div");
                card.className = "card";
                card.innerHTML = `
                    <a href="${escapeHtml(n.link)}" target="_blank" style="text-decoration:none; color:inherit;">
                        <h3>${escapeHtml(n.title)}</h3>
                        <p>${escapeHtml(n.summary)}</p>
                        <div class="meta">
                            <span>${escapeHtml(n.source)}</span>
                            <span>${n.date}</span>
                        </div>
                    </a>
                `;
                newsGrid.appendChild(card);
            });

            state.offset += data.length;
            moreBtn.classList.toggle("hidden", data.length < state.limit);
        } catch (err) {
            console.error(err);
            if (reset) newsGrid.innerHTML = `<div class="loader" style="color:#ef4444;">❌ Ошибка: ${err.message}</div>`;
        }
    }

    // 🔹 Обработчики
    langPicker.addEventListener("click", e => {
        if (!e.target.classList.contains("lang-btn")) return;
        langPicker.querySelectorAll(".lang-btn").forEach(b => b.classList.remove("active"));
        e.target.classList.add("active");
        state.lang = e.target.dataset.lang;
        fetchNews(true);
    });

    dateStrip.addEventListener("click", e => {
        if (!e.target.classList.contains("date-btn")) return;
        dateStrip.querySelectorAll(".date-btn").forEach(b => b.classList.remove("active"));
        e.target.classList.add("active");
        state.date = e.target.dataset.date;
        fetchNews(true);
    });

    moreBtn.addEventListener("click", () => fetchNews(false));

    // 🔹 Инициализация
    renderDateButtons();
    fetchNews(true);
});

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}
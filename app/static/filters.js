const filters = document.querySelector(".filters");

if (filters) {
  const search = filters.elements.q;
  const source = filters.elements.source;
  let searchTimer;

  const submitFilters = () => {
    filters.requestSubmit();
  };

  const scheduleSearch = () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(submitFilters, 300);
  };

  filters.dataset.autoSubmit = "true";
  search.addEventListener("input", (event) => {
    if (!event.isComposing) {
      scheduleSearch();
    }
  });
  search.addEventListener("compositionend", scheduleSearch);
  source.addEventListener("change", () => {
    window.clearTimeout(searchTimer);
    submitFilters();
  });
  filters.addEventListener("submit", () => {
    window.clearTimeout(searchTimer);
  });
}

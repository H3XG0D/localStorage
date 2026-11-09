// Soft hover feedback only — downloads are plain links.
document.querySelectorAll(".btn").forEach((el) => {
  el.addEventListener("pointerenter", () => {
    el.style.boxShadow = "0 8px 24px rgba(61, 207, 122, 0.25)";
  });
  el.addEventListener("pointerleave", () => {
    el.style.boxShadow = "";
  });
});

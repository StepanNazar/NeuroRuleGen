// Timeline navigation is regular links/forms; Bootstrap handles shared controls.
document.querySelectorAll('.timeline-event').forEach((event, index) => {
  event.id = `event-${index + 1}`;
});

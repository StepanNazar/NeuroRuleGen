import { html, parse } from 'diff2html';
import 'diff2html/bundles/css/diff2html.min.css';
import '../css/analysis_result.css';

const data = JSON.parse(document.getElementById('diff-data').textContent);
const container = document.getElementById('pr-diff');
const files = parse(data.diff);
const narrow = matchMedia('(max-width: 767px)');

function renderDiff() {
  container.innerHTML = html(files, {
    outputFormat: narrow.matches ? 'line-by-line' : 'side-by-side',
    drawFileList: false,
    matching: 'lines',
  });
  const wrappers = [...container.querySelectorAll('.d2h-file-wrapper')];
  // diff2html's parsed blocks retain old/new line numbers. Map them onto DOM rows
  // to attach findings to their exact file, side and ending line after each redraw.
  files.forEach((file, index) => {
    const wrapper = wrappers[index];
    const matchingFindings = data.findings.filter(
      (f) => f.file === file.newName || f.file === file.oldName,
    );
    matchingFindings.forEach((finding) => {
      const panels = [...wrapper.querySelectorAll('.d2h-file-side-diff')];
      const panel = narrow.matches ? wrapper : panels[finding.side === 'old' ? 0 : 1];
      if (!panel) return;
      const rows = [...panel.querySelectorAll('tbody > tr')];
      const numberClass = narrow.matches
        ? finding.side === 'old'
          ? '.line-num1'
          : '.line-num2'
        : '.d2h-code-side-linenumber';
      const row = rows.find(
        (r) => Number(r.querySelector(numberClass)?.textContent.trim()) === finding.end,
      );
      if (!row) return;
      const commentRow = document.createElement('tr');
      commentRow.className = 'finding-row';
      const cell = document.createElement('td');
      cell.colSpan = 4;
      const box = document.createElement('div');
      box.className = 'alert alert-primary m-2';
      const title = document.createElement('strong');
      title.textContent = `Finding · ${finding.file}:${finding.start}${finding.end === finding.start ? '' : `–${finding.end}`}`;
      title.className = 'd-block small mb-2';
      const text = document.createElement('p');
      text.className = 'mb-3';
      text.textContent = finding.description;
      const link = document.createElement('a');
      link.className = 'btn btn-sm btn-secondary';
      link.href = `${container.dataset.generationUrl}?description=${encodeURIComponent(finding.description)}`;
      link.textContent = 'Generate a rule for this finding';
      box.append(title, text, link);
      cell.append(box);
      commentRow.append(cell);
      row.after(commentRow);
    });
  });
}
renderDiff();
narrow.addEventListener('change', renderDiff);

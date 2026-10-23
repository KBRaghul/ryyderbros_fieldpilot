import { useRef, useState } from "react";

const PAGES = {
  about: {
    title: "About us",
    body: (
      <>
        <p>
          RyyderBros Field Pilot is an AI crop scouting tool for Alabama corn
          and cotton fields.
        </p>
        <p>
          It combines Sentinel-2 satellite imagery, weather records, USDA soil
          surveys, and county yield history. It shows crop health, finds weaker
          parts of a field, and estimates yield. An AI assistant explains the
          results and answers questions. Every number in an AI answer is checked
          against the source data before it is shown.
        </p>
        <p>
          Field Pilot is a portfolio and research project built by RyyderBros.
        </p>
      </>
    ),
  },
  howto: {
    title: "How to use",
    body: (
      <ol>
        <li>Select a field from the list at the top of the page.</li>
        <li>
          Read the four key numbers: peak crop greenness, yield estimate, water
          balance, and the low-productivity zone.
        </li>
        <li>
          Examine the map. Hover over a colored zone to see its share of the
          field and its acres.
        </li>
        <li>
          Open <strong>Overview</strong> to see crop health through the season
          and the weather factors behind the yield estimate.
        </li>
        <li>
          Open <strong>Report</strong> and select Generate report for a written
          scouting report.
        </li>
        <li>
          Open <strong>Ask Field Pilot</strong> to ask questions in your own
          words, or select an example question.
        </li>
        <li>
          Open <strong>Data</strong> to see monthly weather and soil details.
        </li>
      </ol>
    ),
  },
  privacy: {
    title: "Privacy policy",
    body: (
      <>
        <p>
          Field Pilot does not ask for accounts, names, or contact details, and
          it does not use advertising or tracking cookies.
        </p>
        <p>
          Questions you type in Ask Field Pilot are sent to our AI provider
          (Groq) to produce an answer. Requests may also be recorded in our
          monitoring tool (LangSmith) and in our hosting provider's logs
          (Render) so we can fix errors and improve answer quality.
        </p>
        <p>Do not enter personal or sensitive information in your questions.</p>
        <p>
          Chat history is kept only for your current session and is not linked
          to you.
        </p>
      </>
    ),
  },
  terms: {
    title: "Terms and conditions",
    body: (
      <>
        <p>
          Field Pilot is a demonstration tool, provided as is, without any
          warranty.
        </p>
        <p>
          Yield estimates are county-level estimates based on weather. They are
          not a guarantee of the yield of an individual field. AI answers can be
          incomplete or wrong.
        </p>
        <p>
          Do not use Field Pilot as the only basis for farming, financial, or
          insurance decisions. Speak with an agronomist or your local extension
          office before you make decisions.
        </p>
        <p>
          Data comes from public sources: Microsoft Planetary Computer,
          Open-Meteo, NASA POWER, USDA NASS, and USDA SSURGO. Their own terms
          apply.
        </p>
      </>
    ),
  },
};

export default function Footer() {
  const dialogRef = useRef(null);
  const [page, setPage] = useState(null);

  function open(key) {
    setPage(key);
    dialogRef.current?.showModal();
  }

  return (
    <footer className="site-footer">
      <p className="footer-brand">
        © {new Date().getFullYear()} RyyderBros Field Pilot
      </p>
      <nav aria-label="Footer">
        <ul className="footer-links">
          <li>
            <button type="button" onClick={() => open("about")}>
              About us
            </button>
          </li>
          <li>
            <button type="button" onClick={() => open("howto")}>
              How to use
            </button>
          </li>
          <li>
            <button type="button" onClick={() => open("privacy")}>
              Privacy policy
            </button>
          </li>
          <li>
            <button type="button" onClick={() => open("terms")}>
              Terms and conditions
            </button>
          </li>
        </ul>
      </nav>

      <dialog
        ref={dialogRef}
        className="info-dialog"
        aria-labelledby="info-title"
        onClose={() => setPage(null)}
      >
        {page && (
          <>
            <h2 id="info-title">{PAGES[page].title}</h2>
            <div className="info-body">{PAGES[page].body}</div>
            <form method="dialog">
              <button
                className="btn"
                style={{ width: "auto", padding: "0 24px" }}
              >
                Close
              </button>
            </form>
          </>
        )}
      </dialog>
    </footer>
  );
}

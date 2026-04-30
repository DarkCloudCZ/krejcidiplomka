import React, { useState, useEffect, useRef } from "react";
import "./App.css";

// localStorage cache helpers
const CACHE_KEY = "mbdb_reviewer_cache";
const TOKEN_CACHE_KEY = "mbdb_reviewer_token_cache";
const THEME_CACHE_KEY = "mbdb_reviewer_theme";

function loadFromCache() {
  try {
    const cached = localStorage.getItem(CACHE_KEY);
    return cached ? JSON.parse(cached) : null;
  } catch {
    return null;
  }
}

function saveToCache(data: object) {
  localStorage.setItem(CACHE_KEY, JSON.stringify(data));
}

function clearCache() {
  localStorage.removeItem(CACHE_KEY);
}

function loadTokenFromCache() {
  try {
    const cached = localStorage.getItem(TOKEN_CACHE_KEY);
    return cached ? JSON.parse(cached) : { token: "", keepToken: false };
  } catch {
    return { token: "", keepToken: false };
  }
}

function saveTokenToCache(token: string, keepToken: boolean) {
  if (keepToken) {
    localStorage.setItem(TOKEN_CACHE_KEY, JSON.stringify({ token, keepToken }));
  } else {
    localStorage.removeItem(TOKEN_CACHE_KEY);
  }
}

function loadThemeFromCache(): "dark" | "light" {
  try {
    const cached = localStorage.getItem(THEME_CACHE_KEY);
    if (cached === "light" || cached === "dark") return cached;

    // Fallback to system preference
    return window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  } catch {
    return "dark";
  }
}

function saveThemeToCache(theme: "dark" | "light") {
  localStorage.setItem(THEME_CACHE_KEY, theme);
}

type Issue = {
  path: string;
  severity: string;
  message: string;
  category?: string;
  raw?: string;
  line?: number;
  details?: string;
  value?: string;
  suggested_fix?: string;
  validator?: string;
  expected_range?: string;
  isDone?: boolean;
};

// Available validators with help text
const VALIDATORS = [
  { id: "text", label: "Text quality", type: "AI",
    help: "Checks spelling and grammar in all text fields (descriptions, names, titles). Uses LLM to detect typos, grammatical errors, and language issues. Ignores scientific terms, chemical names, and identifiers." },
  { id: "numeric", label: "Numeric ranges", type: "AI",
    help: "Validates numeric values are within expected ranges: pH (0-14), temperature (-80�C to 150�C for lab conditions), concentrations (positive values), molecular weights. Flags suspicious values like pH=74 (likely 7.4)." },
  { id: "measurement_name", label: "Measurement name vs content", type: "AI",
    help: "Compares measurement names against actual sample content. Flags contradictions like name saying '100 �M BSA' when sample contains different entity or concentration. Does NOT flag missing info - only actual contradictions." },
  { id: "semantic_coherence", label: "Semantic coherence", type: "AI",
    help: "Cross-cutting coherence check: Does technique match protocol text? Do temperature values agree? Does instrument match method? Are results plausible for the concentration range tested? Checks the whole record tells a consistent story." },
  { id: "chem_env_name", label: "Chem env name vs content", type: "AI",
    help: "Checks if chemical environment names match their actual constituents. Catches contradictions like name saying 'NaCl 150 mM' when actual concentration is 100 mM. Does NOT flag if name simply omits some constituents." },
  { id: "required_fields", label: "Required fields", type: "Rules",
    help: "Checks essential fields are present and non-empty: record title, entities of interest, depositor information. Warns if chemical environments or results are missing (may be work in progress)." },
  { id: "date_consistency", label: "Date consistency", type: "Rules",
    help: "Cross-field: Validates date ordering - deposition date must be before availability date. Warns if availability date is more than 1 year in the future. Checks date format is valid (YYYY-MM-DD)." },
  { id: "data_analysis_refs", label: "Data analysis refs", type: "Rules",
    help: "Cross-field: Verifies data_analysis section references valid measurement and result IDs. Catches orphaned references that point to non-existent measurements or results." },
  { id: "entity_usage", label: "Entity usage", type: "Rules",
    help: "Cross-field: Checks entity consistency - warns if entities are defined but never used in measurements, flags references to undefined entities, catches name mismatches between definition and usage." },
  { id: "unit_consistency", label: "Unit consistency", type: "Rules",
    help: "Cross-field: Validates concentration units are valid (nM, �M, mM, mg/mL - not volume units like mL). Warns if same entity uses different units across measurements (e.g., �M in one place, nM in another)." },
  { id: "result_plausibility", label: "Result plausibility", type: "Rules",
    help: "Cross-field: Checks result entities exist in entities_of_interest, validates KD units are appropriate (nM, �M, etc.), warns if error range is larger than measured value." },
  { id: "external_ids", label: "External ID format", type: "Rules",
    help: "Validates format of external identifiers: ORCID (orcid:XXXX-XXXX-XXXX-XXXX, no URL prefix), InChI keys (no space after colon), UniProt (6 or 10 alphanumeric chars), PDB (4 chars), TaxID (digits only)." },
  { id: "whitespace", label: "Whitespace issues", type: "Rules",
    help: "Checks for whitespace problems in names, titles, and identifiers: leading/trailing spaces (e.g., ' LM2023042' or 'ITC buffer '), multiple consecutive spaces. Suggests trimmed values as fixes." },
  { id: "placeholder_values", label: "Placeholder values", type: "Rules",
    help: "Detects -1 placeholder values in numeric fields (concentrations, reference_power, volumes). Also flags any negative concentration which is always invalid. Deterministic check, no LLM." },
  { id: "sequence_content", label: "Sequence content", type: "Rules",
    help: "Validates sequence contains only valid amino acids/nucleotides for polymer type. Proteins: 20 amino acids (ACDEFGHIKLMNPQRSTVWY). DNA: ACGT. RNA: ACGU. Flags numbers and invalid characters." },
  { id: "sequence_mw", label: "Sequence vs MW", type: "Rules",
    help: "Checks if polymer sequence length matches molecular weight. Proteins: ~110 Da per amino acid. DNA: ~330 Da per nucleotide. Uses 15% tolerance. Warns more strongly if no modifications specified. Catches 10x typos in molecular weight." },
];

const ALL_VALIDATOR_IDS = VALIDATORS.map((validator) => validator.id);
type RecordHit = any;

function App() {
  const [recordId, setRecordId] = useState("");
  const [model, setModel] = useState("mst");
  const [useDraft, setUseDraft] = useState(true);
  const [recordJson, setRecordJson] = useState<string>("");
  const [recordList, setRecordList] = useState<RecordHit[] | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [recordSource, setRecordSource] = useState<"draft" | "published" | null>(null);
  const [fallbackUsed, setFallbackUsed] = useState(false);
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [loadingFetch, setLoadingFetch] = useState(false);
  const [loadingValidation, setLoadingValidation] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [selectedValidators, setSelectedValidators] = useState<string[]>(ALL_VALIDATOR_IDS);

  // Sorting and filtering state for issues table
  const [sortField, setSortField] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filterSeverity, setFilterSeverity] = useState<string>("all");
  const [filterValidator, setFilterValidator] = useState<string>("all");
  const [filterDone, setFilterDone] = useState<string>("all");

  // Column visibility state
  const [visibleColumns, setVisibleColumns] = useState({
    checkbox: true,
    line: true,
    validator: false,
    path: true,
    severity: true,
    category: false,
    message: true,
    value: true,
    suggestedFix: true,
    copy: false,
  });

  function toggleColumn(column: keyof typeof visibleColumns) {
    setVisibleColumns((prev) => ({ ...prev, [column]: !prev[column] }));
  }

  // Track completed validators for streaming progress
  const [completedValidators, setCompletedValidators] = useState<string[]>([]);

  // Token state for draft access
  const [mbdbToken, setMbdbToken] = useState("");
  const [keepToken, setKeepToken] = useState(false);

  // Environment selection (staging vs production)
  const [environment, setEnvironment] = useState<"production" | "staging">("staging");

  // Theme state
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  // Refs for dropdowns
  const columnsDropdownRef = useRef<HTMLDetailsElement>(null);

  // Track copied issue for animation
  const [copiedIssueIndex, setCopiedIssueIndex] = useState<number | null>(null);

  // Track highlighted line from click
  const [highlightedLine, setHighlightedLine] = useState<number | null>(null);

  // Ref for JSON viewer section
  const jsonViewerRef = useRef<HTMLDivElement>(null);

  // Load from cache on mount
  useEffect(() => {
    const cached = loadFromCache();
    if (cached) {
      if (cached.recordJson) setRecordJson(cached.recordJson);
      if (cached.selectedRecordId) setSelectedRecordId(cached.selectedRecordId);
      if (cached.issues) setIssues(cached.issues);
      if (cached.model) setModel(cached.model);
      if (cached.environment) setEnvironment(cached.environment);
    }

    // Load token from cache
    const tokenCache = loadTokenFromCache();
    if (tokenCache.keepToken && tokenCache.token) {
      setMbdbToken(tokenCache.token);
      setKeepToken(true);
    }

    // Load theme from cache
    const cachedTheme = loadThemeFromCache();
    setTheme(cachedTheme);
    document.documentElement.setAttribute("data-theme", cachedTheme);
  }, []);

  // Save to cache when state changes
  useEffect(() => {
    if (recordJson || issues) {
      saveToCache({ recordJson, selectedRecordId, issues, model, environment });
    }
  }, [recordJson, selectedRecordId, issues, model, environment]);

  // Auto-save token when keepToken is checked or token changes
  useEffect(() => {
    saveTokenToCache(mbdbToken, keepToken);
  }, [mbdbToken, keepToken]);

  // Save and apply theme when changed
  useEffect(() => {
    saveThemeToCache(theme);
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Close dropdowns when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        columnsDropdownRef.current &&
        !columnsDropdownRef.current.contains(event.target as Node)
      ) {
        columnsDropdownRef.current.open = false;
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  async function fetchRecord(idOverride?: string) {
    setError(null);
    setIssues(null);
    setLoadingFetch(true);

    try {
      const idToUse = (idOverride ?? recordId).trim();

      const resp = await fetch("http://localhost:8000/api/fetch-record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_id: idToUse || null,
          model,
          draft: useDraft,
          token: mbdbToken || null,
          environment,
        }),
      });

      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Backend error ${resp.status}: ${txt}`);
      }

      const data = await resp.json();

      if (data.mode === "detail") {
        setRecordJson(JSON.stringify(data.record, null, 2));
        setRecordList(null);
        setSelectedRecordId((data.record?.id ?? idToUse) || null);
        setRecordSource(data.source || "published");
        setFallbackUsed(data.fallback_used || false);
        setEditMode(false);
      } else if (data.mode === "list") {
        const hits = Array.isArray(data.hits) ? data.hits : [];
        setRecordList(hits);
        setRecordJson("");
        setSelectedRecordId(null);
        setRecordSource(null);
        setFallbackUsed(false);
        setEditMode(false);
      } else {
        throw new Error("Unexpected response mode from backend");
      }
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoadingFetch(false);
    }
  }

  async function runValidation() {
    if (!recordJson || selectedValidators.length === 0) return;
    setError(null);
    setLoadingValidation(true);
    setIssues([]);  // Start with empty array, append as results stream in
    setCompletedValidators([]);

    try {
      const parsed = JSON.parse(recordJson);

      const response = await fetch("http://localhost:8000/api/validate-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_json: parsed,
          validators: selectedValidators,
        }),
      });

      if (!response.ok) {
        const txt = await response.text();
        throw new Error(`Backend error ${response.status}: ${txt}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error("No response body");
      }

      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";  // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const jsonStr = line.slice(6);
            try {
              const data = JSON.parse(jsonStr);

              if (data.done) {
                // All validators complete
                break;
              }

              if (data.issues && Array.isArray(data.issues)) {
                // Append new issues
                setIssues(prev => [...(prev || []), ...data.issues]);
                if (data.validator) {
                  setCompletedValidators(prev => [...prev, data.validator]);
                }
              }

              if (data.error) {
                console.error(`Validator ${data.validator} error:`, data.error);
              }
            } catch (e) {
              console.error("Failed to parse SSE data:", jsonStr);
            }
          }
        }
      }
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoadingValidation(false);
    }
  }

  function toggleValidator(id: string) {
    setSelectedValidators((prev) =>
      prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]
    );
  }

  // Validator selection helpers
  function selectAllValidators() {
    setSelectedValidators(ALL_VALIDATOR_IDS);
  }

  function deselectAllValidators() {
    setSelectedValidators([]);
  }

  function selectGroupValidators(type: string) {
    const groupIds = VALIDATORS.filter(v => v.type === type).map(v => v.id);
    setSelectedValidators(prev => [...new Set([...prev, ...groupIds])]);
  }

  function deselectGroupValidators(type: string) {
    const groupIds = VALIDATORS.filter(v => v.type === type).map(v => v.id);
    setSelectedValidators(prev => prev.filter(id => !groupIds.includes(id)));
  }

  // Sorting and filtering for issues
  function handleSort(field: string) {
    if (sortField === field) {
      setSortDir(prev => prev === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  }

  function getSortedAndFilteredIssues(): Issue[] {
    if (!issues) return [];

    let result = [...issues];

    // Filter by severity
    if (filterSeverity !== "all") {
      result = result.filter(i => i.severity?.toLowerCase() === filterSeverity);
    }

    // Filter by validator
    if (filterValidator !== "all") {
      result = result.filter(i => i.validator === filterValidator);
    }

    // Filter by done status
    if (filterDone === "active") {
      result = result.filter(i => !i.isDone);
    } else if (filterDone === "done") {
      result = result.filter(i => i.isDone);
    }

    // Sort
    if (sortField) {
      result.sort((a, b) => {
        const aVal = (a as any)[sortField] ?? "";
        const bVal = (b as any)[sortField] ?? "";
        const cmp = String(aVal).localeCompare(String(bVal), undefined, { numeric: true });
        return sortDir === "asc" ? cmp : -cmp;
      });
    }

    return result;
  }

  const errorCount =
    issues?.filter(
      (i) => i.severity && i.severity.toLowerCase() === "error",
    ).length ?? 0;
  const warningCount =
    issues?.filter(
      (i) => i.severity && i.severity.toLowerCase() === "warning",
    ).length ?? 0;
  const doneCount = issues?.filter((i) => i.isDone).length ?? 0;
  const activeCount = (issues?.length ?? 0) - doneCount;

  const jsonLines = recordJson ? recordJson.split("\n") : [];

  function getSeverityClass(severity: string) {
    const s = severity?.toLowerCase();
    if (s === "error") return "severity-error";
    if (s === "warning") return "severity-warning";
    return "";
  }

  // Export helper
  function downloadFile(content: string, filename: string, type: string) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Export to CSV
  function exportToCSV() {
    if (!issues || issues.length === 0) return;
    const headers = ["Line", "Validator", "Path", "Severity", "Category", "Message", "Value", "Suggested Fix"];
    const rows = issues.map(i => [
      i.line ?? "",
      i.validator ?? "",
      i.path,
      i.severity,
      i.category ?? "",
      i.message,
      i.value ?? "",
      i.suggested_fix ?? i.expected_range ?? i.details ?? ""
    ]);

    const csv = [headers, ...rows]
      .map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(","))
      .join("\n");
    downloadFile(csv, `validation-${selectedRecordId || "report"}.csv`, "text/csv");
  }

  // Export to JSON
  function exportToJSON() {
    if (!issues) return;
    const report = {
      recordId: selectedRecordId,
      model: model,
      timestamp: new Date().toISOString(),
      summary: {
        total: issues.length,
        errors: errorCount,
        warnings: warningCount
      },
      validators: selectedValidators,
      issues: issues
    };
    downloadFile(JSON.stringify(report, null, 2), `validation-${selectedRecordId || "report"}.json`, "application/json");
  }

  // Toggle theme
  function toggleTheme() {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }

  // Toggle individual issue done status
  function toggleIssueDone(issue: Issue) {
    setIssues((prev) => {
      if (!prev) return prev;
      return prev.map((i) =>
        i === issue ? { ...i, isDone: !i.isDone } : i
      );
    });
  }

  // Toggle all issues done status
  function toggleAllIssues() {
    const allDone = issues?.every((i) => i.isDone);
    setIssues((prev) => prev?.map((i) => ({ ...i, isDone: !allDone })) || null);
  }

  // Scroll to line in JSON viewer
  function scrollToLine(lineNumber: number | undefined) {
    if (!lineNumber || !jsonViewerRef.current) return;

    // Find the line element
    const lineElement = jsonViewerRef.current.querySelector(
      `.json-line:nth-child(${lineNumber})`
    );

    if (lineElement) {
      // Scroll to the line
      lineElement.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });

      // Highlight the line
      setHighlightedLine(lineNumber);

      // Clear highlight after 3 seconds
      setTimeout(() => setHighlightedLine(null), 3000);
    }
  }

  // Copy issue to clipboard
  function copyIssueToClipboard(issue: Issue, index: number) {
    const issueText = `Issue: ${issue.message}
Path: ${issue.path}
Severity: ${issue.severity}${issue.line ? `\nLine: ${issue.line}` : ""}${issue.validator ? `\nValidator: ${issue.validator}` : ""}${issue.category ? `\nCategory: ${issue.category}` : ""}${issue.value ? `\nValue: ${issue.value}` : ""}${issue.suggested_fix || issue.expected_range || issue.details ? `\nSuggested Fix: ${issue.suggested_fix || issue.expected_range || issue.details}` : ""}`;

    navigator.clipboard.writeText(issueText).then(
      () => {
        // Show success animation
        setCopiedIssueIndex(index);
        setTimeout(() => setCopiedIssueIndex(null), 2000);
      },
      (err) => {
        console.error("Failed to copy issue:", err);
      }
    );
  }


  return (
    <div className="app-root">
      {/* Header */}
      <header className="app-header">
        <h1>MBDB Review Tool</h1>
        <span className="app-subtitle">Load records from MBDB and run AI-powered validations</span>
        <button
          onClick={toggleTheme}
          className="theme-toggle"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="4"/>
              <path d="M12 2v2"/>
              <path d="M12 20v2"/>
              <path d="m4.93 4.93 1.41 1.41"/>
              <path d="m17.66 17.66 1.41 1.41"/>
              <path d="M2 12h2"/>
              <path d="M20 12h2"/>
              <path d="m6.34 17.66-1.41 1.41"/>
              <path d="m19.07 4.93-1.41 1.41"/>
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
            </svg>
          )}
        </button>
      </header>

      {/* Token input section */}
      <div className="token-section">
        <div className="token-container">
          <select
            value={environment}
            onChange={(e) => setEnvironment(e.target.value as "production" | "staging")}
            className="token-input"
            style={{ maxWidth: "150px" }}
          >
            <option value="production">Production</option>
            <option value="staging">Staging</option>
          </select>
          <label className="token-label">
            MBDB Token:
            <span className="help-tooltip">
              ?
              <span className="tooltip-text">for draft records</span>
            </span>
            <input
              type="password"
              value={mbdbToken}
              onChange={(e) => setMbdbToken(e.target.value)}
              placeholder="Leave empty to use .env default"
              className="token-input"
            />
          </label>
          <label className="checkbox-inline">
            <input
              type="checkbox"
              checked={keepToken}
              onChange={(e) => setKeepToken(e.target.checked)}
            />
            <span>Keep token cached</span>
          </label>
          {!mbdbToken && (
            <span className="badge badge-info">
              Using .env token (if set) - provides access to drafts and privileged records
            </span>
          )}
          {mbdbToken && (
            <span className="badge badge-info">
              Using custom token - access to drafts and privileged records
            </span>
          )}
        </div>
      </div>

      {/* 1. Select record */}
      <section className="panel">
        <div className="panel-header">
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flex: 1 }}>
            <span>1. Select record</span>
            {fallbackUsed && (
              <span className="badge badge-warning">
                Draft unavailable - showing published version (check token or permissions)
              </span>
            )}
            {recordList && recordList.length > 0 && (
              <span className={`badge ${mbdbToken ? "badge-info" : "badge-warning"}`}>
                {mbdbToken
                  ? "Showing records with authentication"
                  : "Showing public records only (no token)"}
              </span>
            )}
          </div>
          {(recordJson || issues) && (
            <button
              type="button"
              className="btn-clear"
              onClick={() => {
                clearCache();
                setRecordJson("");
                setSelectedRecordId(null);
                setRecordSource(null);
                setFallbackUsed(false);
                setIssues(null);
                setRecordList(null);
                setError(null);
              }}
            >
              Clear All
            </button>
          )}
        </div>
        <div className="panel-body">
          <form
            className="form-inline"
            onSubmit={(e) => {
              e.preventDefault();
              fetchRecord();
            }}
          >
            <select
              value={model}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                setModel(e.target.value)
              }
              className="input input-narrow"
            >
              <option value="mst">MST</option>
              <option value="bli">BLI</option>
              <option value="itc">ITC</option>
              <option value="spr">SPR</option>
            </select>
            <label className="checkbox-inline">
              <input
                type="checkbox"
                checked={useDraft}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setUseDraft(e.target.checked)
                }
              />
              <span>Draft</span>
            </label>
            {useDraft && (
              <input
                value={recordId}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setRecordId(e.target.value)
                }
                className="input"
                placeholder="Record ID (required for draft)"
                required
              />
            )}
            {!useDraft && (
              <input
                value={recordId}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setRecordId(e.target.value)
                }
                className="input"
                placeholder="Record ID (optional - leave empty for list)"
              />
            )}
            <button type="submit" className="btn btn-primary" disabled={loadingFetch}>
              {loadingFetch ? "Fetching..." : "Fetch"}
            </button>
          </form>

          {error && (
            <div className="alert alert-error">
              <strong>Error:</strong> {error}
            </div>
          )}

          {Array.isArray(recordList) && recordList.length > 0 && (
            <div className="record-list">
              <div className="record-list-header">
                <span>Records list</span>
                <span className="record-list-count">
                  {recordList.length} record{recordList.length !== 1 ? "s" : ""}
                </span>
              </div>
              <div className="table-wrapper">
                <table className="table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th style={{ width: "90px" }}>State</th>
                      <th>Title</th>
                      <th style={{ width: "80px" }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recordList.map((hit, idx) => (
                      <tr key={hit.id ?? idx}>
                        <td><code>{hit.id}</code></td>
                        <td>
                          <span className="badge badge-source badge-published badge-inline">
                            published
                          </span>
                        </td>
                        <td className="cell-title">
                          {hit.metadata?.general_parameters?.record_information?.title
                            ?? hit.metadata?.title
                            ?? hit.title
                            ?? <span className="muted">No title</span>}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-secondary btn-small"
                            onClick={() => fetchRecord(hit.id)}
                          >
                            Load
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* 2. JSON viewer */}
      <section className="panel">
        <div className="panel-header">
          <div>
            2. Record JSON
            {selectedRecordId && (
              <span className="badge">
                <code>{selectedRecordId}</code>
              </span>
            )}
            {recordSource && (
              <span className={`badge badge-source ${recordSource === "draft" ? "badge-draft" : "badge-published"}`}>
                {recordSource}
              </span>
            )}
          </div>
          <div className="panel-header-right">
            <button
              type="button"
              className="btn btn-secondary btn-small"
              onClick={() => setEditMode(!editMode)}
              disabled={!recordJson}
            >
              {editMode ? "View" : "Edit"}
            </button>
          </div>
        </div>
        <div className="panel-body">
          {editMode ? (
            <>
              <textarea
                rows={18}
                value={recordJson}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                  setRecordJson(e.target.value)
                }
                className="json-textarea"
                placeholder="Record JSON will appear here after you load a record."
              />
              <p className="muted">
                Edit the JSON directly. Click "View" to see formatted output with line numbers.
              </p>
            </>
          ) : (
            <div className="json-viewer" ref={jsonViewerRef}>
              {jsonLines.length === 0 && (
                <p className="muted">
                  Record JSON will appear here after you load a record.
                </p>
              )}
              {jsonLines.length > 0 && (
                <div className="json-lines">
                  {jsonLines.map((line, index) => {
                    const lineNo = index + 1;
                    const hasIssue =
                      issues &&
                      issues.some(
                        (it) => typeof it.line === "number" && it.line === lineNo,
                      );
                    const isHighlighted = highlightedLine === lineNo;
                    return (
                      <div
                        key={index}
                        className={
                          "json-line" +
                          (hasIssue ? " json-line-issue" : "") +
                          (isHighlighted ? " json-line-highlighted" : "")
                        }
                      >
                        <span className="json-line-number">{lineNo}</span>
                        <span className="json-line-code">
                          {line.length > 0 ? line : " "}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* 3. Validation selector */}
      <section className="panel panel-validators">
        <div className="panel-header">
          <span>3. Select validations</span>
          <div className="validator-toolbar">
            <button type="button" className="btn btn-small btn-secondary" onClick={selectAllValidators}>
              All
            </button>
            <button type="button" className="btn btn-small btn-secondary" onClick={deselectAllValidators}>
              None
            </button>
            <span className="toolbar-divider" />
            <button
              onClick={runValidation}
              className="btn btn-primary btn-small"
              disabled={!recordJson || loadingValidation || selectedValidators.length === 0}
            >
              {loadingValidation
                ? `Running (${completedValidators.length}/${selectedValidators.length})`
                : "Run Validation"}
            </button>
          </div>
        </div>
        <div className="panel-body panel-body-compact">
          {loadingValidation && completedValidators.length > 0 && (
            <div className="validation-progress">
              Completed: {completedValidators.map(v => {
                const validator = VALIDATORS.find(val => val.id === v);
                return validator?.label ?? v;
              }).join(", ")}
            </div>
          )}
          <div className="validator-grid two-columns">
            <div className="validator-group ai-group">
              <div className="validator-group-title">
                <span className="group-icon">AI</span>
                <span>AI Validators</span>
                <div className="group-actions">
                  <button type="button" onClick={() => selectGroupValidators("AI")}>All</button>
                  <button type="button" onClick={() => deselectGroupValidators("AI")}>None</button>
                </div>
              </div>
              {VALIDATORS.filter((v) => v.type === "AI").map((v) => (
                <label key={v.id} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={selectedValidators.includes(v.id)}
                    onChange={() => toggleValidator(v.id)}
                  />
                  <span className="validator-label">{v.label}</span>
                  <span className="help-tooltip">
                    ?
                    <span className="tooltip-text">{v.help}</span>
                  </span>
                </label>
              ))}
            </div>
            <div className="validator-group rules-group">
              <div className="validator-group-title">
                <span className="group-icon">R</span>
                <span>Rule-based</span>
                <div className="group-actions">
                  <button type="button" onClick={() => selectGroupValidators("Rules")}>All</button>
                  <button type="button" onClick={() => deselectGroupValidators("Rules")}>None</button>
                </div>
              </div>
              {VALIDATORS.filter((v) => v.type === "Rules").map((v) => (
                <label key={v.id} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={selectedValidators.includes(v.id)}
                    onChange={() => toggleValidator(v.id)}
                  />
                  <span className="validator-label">{v.label}</span>
                  <span className="help-tooltip">
                    ?
                    <span className="tooltip-text">{v.help}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 4. Validation issues */}
      <section className="panel panel-issues">
        <div className="panel-header panel-header-wrap">
          <div className="panel-header-left">
            <span>4. Issues</span>
            {issues && (
              <span className="issues-summary">
                {activeCount} active, {doneCount} resolved ({errorCount} error{errorCount !== 1 ? "s" : ""}, {warningCount} warning{warningCount !== 1 ? "s" : ""})
              </span>
            )}
          </div>
          {issues && issues.length > 0 && (
            <div className="issues-header-controls">
              <select
                value={filterSeverity}
                onChange={(e) => setFilterSeverity(e.target.value)}
                className="filter-select"
              >
                <option value="all">All severities</option>
                <option value="error">Errors only</option>
                <option value="warning">Warnings only</option>
              </select>
              <select
                value={filterValidator}
                onChange={(e) => setFilterValidator(e.target.value)}
                className="filter-select"
              >
                <option value="all">All validators</option>
                {VALIDATORS.map((v) => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
              </select>
              <select
                value={filterDone}
                onChange={(e) => setFilterDone(e.target.value)}
                className="filter-select"
              >
                <option value="all">All issues</option>
                <option value="active">Active only</option>
                <option value="done">Resolved only</option>
              </select>
              <span className="filter-count">
                {getSortedAndFilteredIssues().length}/{issues.length}
              </span>
              <span className="toolbar-divider" />
              <details className="columns-toggle" ref={columnsDropdownRef}>
                <summary>Columns</summary>
                <div className="columns-dropdown">
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.checkbox}
                      onChange={() => toggleColumn("checkbox")}
                    />
                    <span>Checkbox</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.line}
                      onChange={() => toggleColumn("line")}
                    />
                    <span>Line</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.validator}
                      onChange={() => toggleColumn("validator")}
                    />
                    <span>Validator</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.path}
                      onChange={() => toggleColumn("path")}
                    />
                    <span>Path</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.severity}
                      onChange={() => toggleColumn("severity")}
                    />
                    <span>Severity</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.category}
                      onChange={() => toggleColumn("category")}
                    />
                    <span>Category</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.message}
                      onChange={() => toggleColumn("message")}
                    />
                    <span>Message</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.value}
                      onChange={() => toggleColumn("value")}
                    />
                    <span>Value</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.suggestedFix}
                      onChange={() => toggleColumn("suggestedFix")}
                    />
                    <span>Suggested Fix</span>
                  </label>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={visibleColumns.copy}
                      onChange={() => toggleColumn("copy")}
                    />
                    <span>Copy</span>
                  </label>
                </div>
              </details>
              <span className="toolbar-divider" />
              <button type="button" className="btn btn-small btn-secondary" onClick={exportToCSV}>
                CSV
              </button>
              <button type="button" className="btn btn-small btn-secondary" onClick={exportToJSON}>
                JSON
              </button>
            </div>
          )}
        </div>
        <div className="panel-body panel-body-tight">
          {!issues && <p className="muted">No validation run yet.</p>}

          {issues && issues.length === 0 && (
            <div className="alert alert-success">
              No issues found for this record.
            </div>
          )}

          {issues && issues.length > 0 && (
            <div className="table-wrapper">
              <table className="table issues-table">
                <thead>
                  <tr>
                    {visibleColumns.checkbox && (
                      <th className="col-checkbox">
                        <input
                          type="checkbox"
                          checked={issues?.every((i) => i.isDone) || false}
                          onChange={toggleAllIssues}
                          aria-label="Toggle all issues"
                        />
                      </th>
                    )}
                    {visibleColumns.line && (
                      <th className="sortable col-line" onClick={() => handleSort("line")}>
                        Line {sortField === "line" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                    )}
                    {visibleColumns.validator && (
                      <th className="sortable col-validator" onClick={() => handleSort("validator")}>
                        Validator {sortField === "validator" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                    )}
                    {visibleColumns.path && (
                      <th className="sortable col-path" onClick={() => handleSort("path")}>
                        Path {sortField === "path" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                    )}
                    {visibleColumns.severity && (
                      <th className="sortable col-severity" onClick={() => handleSort("severity")}>
                        Severity {sortField === "severity" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                    )}
                    {visibleColumns.category && (
                      <th className="sortable col-category" onClick={() => handleSort("category")}>
                        Category {sortField === "category" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                    )}
                    {visibleColumns.message && <th className="col-message">Message</th>}
                    {visibleColumns.value && <th className="col-value">Value</th>}
                    {visibleColumns.suggestedFix && <th className="col-fix">Suggested Fix</th>}
                    {visibleColumns.copy && <th className="col-copy">Copy</th>}
                  </tr>
                </thead>
                <tbody>
                  {getSortedAndFilteredIssues().map((it, idx) => (
                    <tr
                      key={idx}
                      className={it.isDone ? "issue-done" : ""}
                      onClick={() => scrollToLine(it.line)}
                      style={{ cursor: it.line ? "pointer" : "default" }}
                    >
                      {visibleColumns.checkbox && (
                        <td className="col-checkbox" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={it.isDone || false}
                            onChange={() => toggleIssueDone(it)}
                            aria-label={`Mark issue as ${it.isDone ? "not done" : "done"}`}
                          />
                        </td>
                      )}
                      {visibleColumns.line && (
                        <td className="col-line">{typeof it.line === "number" ? it.line : "-"}</td>
                      )}
                      {visibleColumns.validator && <td className="col-validator">{it.validator ?? "-"}</td>}
                      {visibleColumns.path && <td className="col-path cell-path">{it.path}</td>}
                      {visibleColumns.severity && (
                        <td className={`col-severity ${getSeverityClass(it.severity)}`}>{it.severity}</td>
                      )}
                      {visibleColumns.category && <td className="col-category">{it.category ?? "-"}</td>}
                      {visibleColumns.message && <td className="col-message">{it.message}</td>}
                      {visibleColumns.value && (
                        <td className="col-value cell-value" title={it.value ?? ""}>{it.value ?? ""}</td>
                      )}
                      {visibleColumns.suggestedFix && (
                        <td className="col-fix">{it.suggested_fix ?? it.expected_range ?? it.details ?? ""}</td>
                      )}
                      {visibleColumns.copy && (
                        <td className="col-copy" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            className={`btn-copy-issue ${copiedIssueIndex === idx ? "copied" : ""}`}
                            onClick={() => copyIssueToClipboard(it, idx)}
                            aria-label="Copy issue to clipboard"
                            title="Copy issue to clipboard"
                          >
                            {copiedIssueIndex === idx ? (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="20 6 9 17 4 12"/>
                              </svg>
                            ) : (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                              </svg>
                            )}
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

export default App;


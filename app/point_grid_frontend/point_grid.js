const pointGridInstances = new WeakMap()

function createPointGridInstance(parentElement) {
  const wrap = parentElement.querySelector(".pg-wrap")
  const gridElement = parentElement.querySelector(".pg-grid")
  const addButton = parentElement.querySelector(".pg-add-row")
  const warning = parentElement.querySelector(".pg-warning")
  if (!wrap || !gridElement || !addButton || !warning) return null

  const state = {
    wrap,
    gridElement,
    addButton,
    warning,
    table: null,
    tableReady: false,
    columns: [],
    columnSpecs: [],
    specByField: new Map(),
    idStart: 1,
    idColumn: null,
    idPrefix: "",
    nextId: 1,
    derivedSize: null,
    defaultValues: {},
    compactPasteFields: [],
    layout: "fitColumns",
    dataVersion: null,
    label: "Editable section points",
    pasteAnchorRow: 0,
    setStateValue: null,
    visibilityTarget: null,
    visibilityObserver: null,
    redrawFrame: null,
    wasVisible: false,
    visibleWidth: 0,
    handleAddRow: null,
    handlePaste: null,
    cleanup: null,
  }

  state.isComplete = row => state.columnSpecs.every(spec => {
    if (spec.type !== "number") return true
    const value = row[spec.field]
    if (value === null || value === undefined || value === "") return false
    return Number.isFinite(Number(value))
  })

  state.isPersistentId = () => Boolean(state.idColumn)

  state.idPattern = () => new RegExp(
    `^${state.idPrefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([1-9][0-9]*)$`,
  )

  state.preparePersistentIds = rows => {
    const used = new Set()
    const pattern = state.idPattern()
    let maximum = 0
    rows.forEach(row => {
      const value = String(row[state.idColumn] ?? "").trim()
      const match = value.match(pattern)
      if (match) maximum = Math.max(maximum, Number(match[1]))
    })
    state.nextId = maximum + 1
    rows.forEach(row => {
      let value = String(row[state.idColumn] ?? "").trim()
      if (!pattern.test(value) || used.has(value)) value = ""
      if (!value) {
        do {
          value = `${state.idPrefix}${state.nextId++}`
        } while (used.has(value))
      }
      used.add(value)
      row[state.idColumn] = value
    })
  }

  state.allocateId = () => {
    const used = new Set(
      state.table
        ? state.table.getData().map(row => String(row[state.idColumn] ?? "").trim())
        : [],
    )
    let value
    do {
      value = `${state.idPrefix}${state.nextId++}`
    } while (used.has(value))
    return value
  }

  state.applyIds = rows => {
    if (state.isPersistentId()) {
      state.preparePersistentIds(rows)
      return
    }
    let nextId = state.idStart
    rows.forEach(row => {
      row._id = state.isComplete(row) ? String(nextId++) : ""
    })
  }

  state.coerceValue = (value, spec) => {
    if (spec.type === "number") {
      const number = Number(value)
      return (
        value === "" || value === null || value === undefined
        || !Number.isFinite(number)
      ) ? null : number
    }
    const text = value === null || value === undefined ? "" : String(value).trim()
    if (spec.type === "select" && Array.isArray(spec.options)) {
      const choice = spec.options.find(
        option => String(option).toLowerCase() === text.toLowerCase(),
      )
      // An imported project may deliberately retain an unresolved catalogue ID
      // so the Python validation can block calculation and tell the user what to
      // repair. Never turn that evidence into the first valid option merely
      // because another cell was edited.
      return choice === undefined ? text : String(choice)
    }
    return text
  }

  state.normaliseSizeRow = row => {
    const fields = state.derivedSize
    if (!fields) return row
    const mode = String(row[fields.mode] ?? "")
    const area = Number(row[fields.area])
    const diameter = Number(row[fields.diameter])
    if (mode === fields.area_mode) {
      row[fields.diameter] = Number.isFinite(area) && area > 0
        ? Math.sqrt(4 * area / Math.PI)
        : null
    } else if (mode === fields.diameter_mode) {
      row[fields.area] = Number.isFinite(diameter) && diameter > 0
        ? Math.PI * diameter * diameter / 4
        : null
    }
    return row
  }

  state.currentRows = () => {
    if (!state.table) return []
    return state.table.getData().map(row => {
      const output = {}
      state.columnSpecs.forEach(spec => {
        output[spec.field] = state.coerceValue(row[spec.field], spec)
      })
      return state.normaliseSizeRow(output)
    })
  }

  state.emit = () => {
    if (!state.table || !state.setStateValue) return
    state.setStateValue("payload", {
      data_version: state.dataVersion,
      rows: state.currentRows(),
    })
  }

  state.setWarning = message => {
    warning.textContent = message || ""
    warning.hidden = !message
  }

  state.clearWarning = () => {
    if (!warning.hidden) state.setWarning("")
  }

  state.refreshDeleteLabels = () => {
    if (!state.table) return
    state.table.getRows().forEach((row, index) => {
      const button = row.getElement().querySelector(".pg-delete-button")
      if (button) {
        button.setAttribute(
          "aria-label",
          `Delete row ${index + 1} from ${state.label}`,
        )
      }
    })
  }

  state.renumber = () => {
    if (!state.table) return
    if (state.isPersistentId()) {
      state.refreshDeleteLabels()
      return
    }
    let nextId = state.idStart
    state.table.getRows().forEach(row => {
      const data = row.getData()
      const id = state.isComplete(data) ? String(nextId++) : ""
      if (data._id !== id) row.update({ _id: id })
    })
    state.refreshDeleteLabels()
  }

  state.formatNumber = cell => {
    const value = cell.getValue()
    if (value === null || value === undefined || value === "") return ""
    const number = Number(value)
    return Number.isFinite(number)
      ? String(parseFloat(number.toFixed(4)))
      : ""
  }

  state.splitPasteLines = text => {
    const lines = text.split(/\r\n|\n|\r/)
    while (lines.length && !lines[lines.length - 1].trim().length) lines.pop()
    return lines
  }

  state.selectEditor = (cell, onRendered, success, cancel, params) => {
    const select = document.createElement("select")
    select.className = "pg-select-editor"
    select.setAttribute(
      "aria-label",
      String(cell.getColumn().getDefinition().title || "Select value"),
    )
    const values = params.values || []
    const current = String(cell.getValue() ?? "")
    const currentIsKnown = values.some(
      value => String(value).toLowerCase() === current.toLowerCase(),
    )
    if (current && !currentIsKnown) {
      const unresolved = document.createElement("option")
      unresolved.value = current
      unresolved.textContent = `${current} (undefined)`
      unresolved.disabled = true
      unresolved.selected = true
      select.appendChild(unresolved)
    }
    values.forEach(value => {
      const option = document.createElement("option")
      option.value = String(value)
      option.textContent = String(value)
      select.appendChild(option)
    })
    select.value = current

    let finished = false
    const commit = () => {
      if (finished) return
      finished = true
      success(select.value)
    }
    const abort = () => {
      if (finished) return
      finished = true
      cancel()
    }
    select.addEventListener("change", commit)
    select.addEventListener("blur", commit)
    select.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        event.preventDefault()
        abort()
      } else if (event.key === "Enter") {
        event.preventDefault()
        commit()
      }
    })
    onRendered(() => select.focus())
    return select
  }

  state.pasteSpecs = () => state.columnSpecs.filter(
    spec => spec.paste !== false && spec.editable !== false,
  )

  state.pasteSpecsForCount = count => {
    const full = state.pasteSpecs()
    if (count === full.length) return full
    if (count === state.compactPasteFields.length) {
      return state.compactPasteFields
        .map(field => state.specByField.get(field))
        .filter(Boolean)
    }
    return null
  }

  state.blankRow = () => {
    const row = {}
    state.columnSpecs.forEach(spec => {
      if (spec.field === state.idColumn) row[spec.field] = state.allocateId()
      else if (Object.hasOwn(state.defaultValues, spec.field)) {
        row[spec.field] = state.coerceValue(state.defaultValues[spec.field], spec)
      } else if (spec.type === "select") {
        row[spec.field] = String(spec.options?.[0] ?? "")
      } else {
        row[spec.field] = spec.type === "number" ? null : ""
      }
    })
    return state.normaliseSizeRow(row)
  }

  state.pasteToEditableColumns = (text, specs = state.pasteSpecs()) => (
    state.splitPasteLines(text).map(line => {
    const cells = line.split("\t")
    const row = {}
    specs.forEach((spec, index) => {
      const raw = cells[index] === undefined ? "" : String(cells[index]).trim()
      row[spec.field] = state.coerceValue(raw, spec)
    })
    return state.normaliseSizeRow(row)
  }))

  state.applyPaste = text => {
    if (!state.table) return
    const lines = state.splitPasteLines(text)
    if (!lines.length) return
    const pastedColumnCount = Math.max(...lines.map(line => line.split("\t").length))
    const pasteSpecs = state.pasteSpecs()
    const selectedSpecs = state.pasteSpecsForCount(pastedColumnCount)
    if (!selectedSpecs) {
      const compact = state.compactPasteFields.length
        ? ` or ${state.compactPasteFields.length} compact geometry columns`
        : ""
      state.setWarning(
        `Pasted block has ${pastedColumnCount} column(s); this table expects `
        + `${pasteSpecs.length} (${pasteSpecs.map(spec => spec.title).join(", ")})`
        + `${compact}. `
        + "Nothing pasted.",
      )
      return
    }

    state.clearWarning()
    const pastedRows = state.pasteToEditableColumns(text, selectedSpecs)
    const mergedRows = state.currentRows()
    const start = Math.min(state.pasteAnchorRow, mergedRows.length)
    pastedRows.forEach((row, index) => {
      const target = start + index
      const existing = mergedRows[target] || state.blankRow()
      const merged = { ...existing, ...row }
      if (state.isPersistentId() && !merged[state.idColumn]) {
        merged[state.idColumn] = state.allocateId()
      }
      mergedRows[target] = state.normaliseSizeRow(merged)
    })
    state.table.setData(mergedRows).then(() => {
      state.renumber()
      state.emit()
    })
  }

  state.buildColumns = () => {
    const definitions = []
    if (!state.isPersistentId()) {
      definitions.push({
        title: "ID",
        field: "_id",
        width: 52,
        hozAlign: "right",
        headerSort: false,
        editable: false,
        clipboard: false,
        frozen: true,
        cssClass: "pg-id",
      })
    }

    state.columnSpecs.forEach(spec => {
      const isNumber = spec.type === "number"
      const isId = spec.type === "id" || spec.field === state.idColumn
      const definition = {
        title: spec.title || spec.field,
        field: spec.field,
        width: Number(spec.width) || undefined,
        minWidth: Number(spec.min_width) || 70,
        headerSort: false,
        headerWordWrap: true,
        hozAlign: isNumber ? "right" : "left",
        editable: isId || spec.editable === false
          ? false
          : cell => {
            const fields = state.derivedSize
            if (!fields || !spec.derived_role) return true
            const mode = String(cell.getRow().getData()[fields.mode] ?? "")
            if (spec.derived_role === "area") return mode !== fields.diameter_mode
            if (spec.derived_role === "diameter") return mode !== fields.area_mode
            return true
          },
        clipboard: spec.paste !== false,
        frozen: isId,
        cssClass: isId
          ? "pg-id"
          : spec.derived_role ? `pg-${spec.derived_role}` : "",
      }
      if (isNumber) {
        definition.editor = "number"
        definition.editorParams = { selectContents: true }
        definition.formatter = state.formatNumber
      } else if (spec.type === "select") {
        definition.editor = state.selectEditor
        definition.editorParams = { values: spec.options || [] }
        definition.formatter = cell => {
          const value = String(cell.getValue() ?? "")
          if (state.derivedSize && spec.field === state.derivedSize.mode) {
            cell.getRow().getElement().setAttribute("data-size-mode", value)
          }
          return value
        }
      } else if (!isId) {
        definition.editor = "input"
        definition.editorParams = { selectContents: true }
      }
      definition.mutatorEdit = value => state.coerceValue(value, spec)
      definitions.push(definition)
    })

    definitions.push({
      title: "",
      field: "_delete",
      width: 38,
      headerSort: false,
      editable: false,
      clipboard: false,
      hozAlign: "center",
      cssClass: "pg-del",
      formatter: cell => {
        const button = document.createElement("button")
        button.type = "button"
        button.className = "pg-delete-button"
        button.textContent = "×"
        button.title = "Delete row"
        button.addEventListener("click", event => {
          event.stopPropagation()
          cell.getRow().delete()
        })
        return button
      },
    })

    return definitions
  }

  state.build = data => {
    state.columns = Array.isArray(data.columns) ? [...data.columns] : []
    const suppliedSpecs = Array.isArray(data.column_specs) ? data.column_specs : []
    const byField = new Map(
      suppliedSpecs
        .filter(spec => spec && spec.field !== undefined)
        .map(spec => [String(spec.field), { ...spec }]),
    )
    state.columnSpecs = state.columns.map(field => ({
      field,
      title: field,
      type: "number",
      ...(byField.get(field) || {}),
    }))
    state.specByField = new Map(
      state.columnSpecs.map(spec => [spec.field, spec]),
    )
    state.idColumn = state.columns.includes(String(data.id_column || ""))
      ? String(data.id_column)
      : null
    state.idPrefix = String(data.id_prefix || "")
    state.derivedSize = data.derived_size && typeof data.derived_size === "object"
      ? { ...data.derived_size }
      : null
    state.defaultValues = data.default_values && typeof data.default_values === "object"
      ? { ...data.default_values }
      : {}
    state.compactPasteFields = Array.isArray(data.compact_paste_fields)
      ? data.compact_paste_fields.filter(field => state.columns.includes(field))
      : []
    state.layout = String(data.layout || "fitColumns")
    const requestedStart = Number(data.id_start)
    state.idStart = Number.isFinite(requestedStart) ? requestedStart : 1
    state.dataVersion = String(data.data_version ?? "0")
    state.label = String(data.label || "Editable section points")
    state.pasteAnchorRow = 0
    state.gridElement.setAttribute("aria-label", state.label)
    state.addButton.setAttribute("aria-label", `Add row to ${state.label}`)

    const rows = Array.isArray(data.rows)
      ? data.rows.map(row => {
        const output = {}
        state.columnSpecs.forEach(spec => {
          output[spec.field] = state.coerceValue(row[spec.field], spec)
        })
        return state.normaliseSizeRow(output)
      })
      : []
    state.applyIds(rows)

    if (state.redrawFrame !== null) {
      cancelAnimationFrame(state.redrawFrame)
      state.redrawFrame = null
    }
    state.tableReady = false
    if (state.table) {
      const oldTable = state.table
      state.table = null
      oldTable.destroy()
    }
    state.gridElement.replaceChildren()

    if (typeof globalThis.Tabulator !== "function") {
      state.setWarning("The point table could not be loaded. Reload Sector and try again.")
      return
    }

    const table = new globalThis.Tabulator(state.gridElement, {
      data: rows,
      layout: state.layout,
      columns: state.buildColumns(),
      height: false,
      clipboard: true,
      clipboardPasteAction: "replace",
      clipboardPasteParser: state.pasteToEditableColumns,
      addRowPos: "bottom",
      reactiveData: false,
    })
    state.table = table

    table.on("tableBuilt", () => {
      if (state.table !== table) return
      state.tableReady = true
      state.refreshDeleteLabels()
      state.redrawIfVisible(true)
    })
    table.on("renderComplete", () => state.refreshDeleteLabels())
    table.on("cellEditing", cell => {
      const position = cell.getRow().getPosition(true)
      state.pasteAnchorRow = position > 0 ? position - 1 : 0
    })
    table.on("cellEdited", cell => {
      state.clearWarning()
      const row = cell.getRow()
      const normalised = state.normaliseSizeRow({ ...row.getData() })
      Promise.resolve(row.update(normalised)).then(() => {
        state.renumber()
        state.emit()
      })
    })
    table.on("rowDeleted", () => {
      state.renumber()
      state.emit()
    })
    table.on("clipboardPasted", () => {
      state.renumber()
      state.emit()
    })
  }

  state.handleAddRow = () => {
    if (!state.table) return
    state.table.addRow(state.blankRow()).then(() => {
      state.renumber()
      state.emit()
    })
  }
  addButton.addEventListener("click", state.handleAddRow)

  state.handlePaste = event => {
    if (!state.table) return
    const clipboard = event.clipboardData
    const text = clipboard ? clipboard.getData("text") : ""
    const isBlock = text.includes("\t") || /\n/.test(text.trim())
    if (!text || !isBlock) return
    event.preventDefault()
    event.stopPropagation()
    state.applyPaste(text)
  }
  wrap.addEventListener("paste", state.handlePaste, { capture: true })

  const root = parentElement.getRootNode()
  state.visibilityTarget = root && root.host ? root.host : wrap
  state.redrawIfVisible = (force = false) => {
    if (!state.table || !state.tableReady || !state.visibilityTarget) return
    const rect = state.visibilityTarget.getBoundingClientRect()
    const visible = rect.width > 0 && rect.height > 0
    const widthChanged = Math.abs(rect.width - state.visibleWidth) > 0.5
    const becameVisible = visible && !state.wasVisible
    state.wasVisible = visible
    state.visibleWidth = visible ? rect.width : 0
    if (!visible || (!force && !becameVisible && !widthChanged)) return
    if (state.redrawFrame !== null) cancelAnimationFrame(state.redrawFrame)
    const table = state.table
    state.redrawFrame = requestAnimationFrame(() => {
      state.redrawFrame = null
      if (state.table === table && state.tableReady) table.redraw(true)
    })
  }
  if (typeof ResizeObserver === "function") {
    state.visibilityObserver = new ResizeObserver(() => state.redrawIfVisible())
    state.visibilityObserver.observe(state.visibilityTarget)
  }

  state.cleanup = () => {
    if (state.visibilityObserver) {
      state.visibilityObserver.disconnect()
      state.visibilityObserver = null
    }
    addButton.removeEventListener("click", state.handleAddRow)
    wrap.removeEventListener("paste", state.handlePaste, true)
    if (state.redrawFrame !== null) {
      cancelAnimationFrame(state.redrawFrame)
      state.redrawFrame = null
    }
    const table = state.table
    state.table = null
    state.tableReady = false
    pointGridInstances.delete(parentElement)
    if (table) table.destroy()
  }

  return state
}

export default function renderPointGrid(component) {
  const { parentElement, data, setStateValue } = component
  if (!parentElement) return

  let state = pointGridInstances.get(parentElement)
  if (!state) {
    state = createPointGridInstance(parentElement)
    if (!state) return
    pointGridInstances.set(parentElement, state)
  }

  state.setStateValue = setStateValue
  const nextData = data || {}
  const nextVersion = String(nextData.data_version ?? "0")
  if (!state.table || nextVersion !== state.dataVersion) {
    state.clearWarning()
    state.build(nextData)
    state.redrawIfVisible(true)
    return state.cleanup
  }

  state.label = String(nextData.label || state.label)
  state.gridElement.setAttribute("aria-label", state.label)
  state.addButton.setAttribute("aria-label", `Add row to ${state.label}`)
  state.refreshDeleteLabels()
  state.redrawIfVisible(true)
  return state.cleanup
}

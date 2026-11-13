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
    idNext: 1,
    separatorRows: false,
    movableRows: false,
    selectedIds: [],
    selectionToken: 0,
    derivedSize: null,
    defaultValues: {},
    compactPasteFields: [],
    layout: "fitColumns",
    dataVersion: null,
    configurationSignature: null,
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

  // A void-table row with every number cell blank separates two voids. It has
  // no ID, so the ID column shows the voids as separate groups.
  state.isSeparator = row => state.separatorRows && state.columnSpecs.every(spec => {
    if (spec.type !== "number") return true
    const value = row[spec.field]
    return value === null || value === undefined || value === ""
  })

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
    // The region counter keeps a deleted number out of use.
    state.nextId = Math.max(maximum + 1, state.idNext, state.nextId || 1)
    rows.forEach(row => {
      let value = String(row[state.idColumn] ?? "").trim()
      if (state.isSeparator(row)) {
        row[state.idColumn] = ""
        return
      }
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

  state.selectDefault = spec => (
    spec.allow_blank ? "" : String(spec.options?.[0] ?? "")
  )

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
      // Some engineering assignments must remain blank until the user makes an
      // explicit choice. Other selects retain their first-option default.
      if (!text.length) return state.selectDefault(spec)
      const choice = spec.options.find(
        option => String(option).toLowerCase() === text.toLowerCase(),
      )
      // An imported project may deliberately retain an unresolved catalogue ID
      // so the Python validation can block calculation and tell the user what to
      // repair. Never turn that evidence into the first valid option merely
      // because another cell was edited.
      return choice === undefined
        ? (spec.preserve_unknown ? text : state.selectDefault(spec))
        : String(choice)
    }
    return text
  }

  // Paste rule: a cell with exactly one comma and no dot is a decimal comma.
  // A non-numeric text stays in the cell as an error cell. It is not a number,
  // so the row is incomplete until the engineer corrects it.
  state.pasteValue = (raw, spec) => {
    if (spec.type !== "number") return state.coerceValue(raw, spec)
    const text = String(raw ?? "").trim()
    if (!text.length) return null
    const commas = (text.match(/,/g) || []).length
    const candidate = commas === 1 && !text.includes(".")
      ? text.replace(",", ".")
      : text
    const number = Number(candidate)
    return Number.isFinite(number) ? number : text
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
    const payload = {
      data_version: state.dataVersion,
      rows: state.currentRows(),
    }
    // The next number of the browser counter, so Python can keep a number that
    // was issued and deleted between two reports out of use.
    if (state.isPersistentId()) payload.next_id = state.nextId
    state.setStateValue("payload", payload)
  }

  state.emitSelection = id => {
    if (!state.setStateValue || !id) return
    state.selectionToken += 1
    state.setStateValue("selection", {
      data_version: state.dataVersion,
      id,
      token: `${Date.now()}-${state.selectionToken}`,
    })
  }

  state.applySelection = ids => {
    state.selectedIds = Array.isArray(ids) ? ids.map(String) : []
    if (!state.table || !state.isPersistentId()) return
    const wanted = new Set(state.selectedIds)
    let first = null
    state.table.getRows().forEach(row => {
      const id = String(row.getData()[state.idColumn] ?? "")
      const element = row.getElement()
      const selected = Boolean(id) && wanted.has(id)
      element.classList.toggle("pg-selected", selected)
      if (selected) element.setAttribute("aria-selected", "true")
      else element.removeAttribute("aria-selected")
      if (selected && first === null) first = row
    })
    if (first !== null && state.tableReady) {
      Promise.resolve(first.scrollTo("nearest", false)).catch(() => {})
    }
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
      if (state.separatorRows) {
        state.table.getRows().forEach(row => {
          const data = row.getData()
          const id = String(data[state.idColumn] ?? "")
          if (state.isSeparator(data)) {
            if (id) row.update({ [state.idColumn]: "" })
          } else if (!id) {
            row.update({ [state.idColumn]: state.allocateId() })
          }
        })
      }
      state.refreshDeleteLabels()
      state.applySelection(state.selectedIds)
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
    const element = cell.getElement()
    const invalid = typeof value === "string" && value.trim().length > 0
      && !Number.isFinite(Number(value))
    element.classList.toggle("pg-invalid", invalid)
    if (invalid) {
      element.setAttribute("title", "Not a number. Enter a number.")
      return value
    }
    element.removeAttribute("title")
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
    if (params.allowBlank) {
      const blank = document.createElement("option")
      blank.value = ""
      blank.textContent = "Select..."
      select.appendChild(blank)
    }
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
      if (spec.field === state.idColumn) {
        row[spec.field] = state.separatorRows ? "" : state.allocateId()
      }
      else if (Object.hasOwn(state.defaultValues, spec.field)) {
        row[spec.field] = state.coerceValue(state.defaultValues[spec.field], spec)
      } else if (spec.type === "select") {
        row[spec.field] = state.selectDefault(spec)
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
      row[spec.field] = state.pasteValue(raw, spec)
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
    // Keep the error text of earlier pastes in the cells.
    const mergedRows = state.table.getData().map(row => ({ ...row }))
    const start = Math.min(state.pasteAnchorRow, mergedRows.length)
    pastedRows.forEach((row, index) => {
      const target = start + index
      const existing = mergedRows[target] || state.blankRow()
      const merged = { ...existing, ...row }
      if (
        state.isPersistentId() && !merged[state.idColumn]
        && !state.isSeparator(merged)
      ) {
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
    if (state.movableRows) {
      definitions.push({
        title: "",
        field: "_move",
        width: 28,
        headerSort: false,
        editable: false,
        clipboard: false,
        frozen: true,
        rowHandle: true,
        formatter: "handle",
        cssClass: "pg-move",
        tooltip: "Drag to move the row",
      })
    }
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
      const help = typeof spec.help === "string" ? spec.help.trim() : ""
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
      if (help) definition.headerTooltip = help
      if (isId && state.isPersistentId()) {
        definition.tooltip = "Select to show this element in the section view"
        definition.cellClick = (_event, cell) => {
          const id = String(cell.getValue() ?? "")
          if (id) state.emitSelection(id)
        }
      }
      if (isNumber) {
        definition.editor = "number"
        definition.editorParams = { selectContents: true }
        definition.formatter = state.formatNumber
      } else if (spec.type === "select") {
        definition.editor = state.selectEditor
        definition.editorParams = {
          values: spec.options || [],
          allowBlank: spec.allow_blank === true,
        }
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

  state.configurationSignatureFor = data => JSON.stringify({
    columns: data.columns || [],
    column_specs: data.column_specs || [],
    id_column: data.id_column || null,
    id_prefix: data.id_prefix || "",
    separator_rows: Boolean(data.separator_rows),
    movable_rows: Boolean(data.movable_rows),
    derived_size: data.derived_size || null,
    default_values: data.default_values || {},
    compact_paste_fields: data.compact_paste_fields || [],
    layout: data.layout || "fitColumns",
    id_start: data.id_start || 1,
  })

  state.configure = data => {
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
    const requestedNext = Number(data.id_next)
    state.idNext = Number.isFinite(requestedNext) && requestedNext >= 1
      ? Math.floor(requestedNext)
      : 1
    state.nextId = Math.max(state.nextId || 1, state.idNext)
    state.separatorRows = Boolean(data.separator_rows)
    state.movableRows = Boolean(data.movable_rows)
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
    state.configurationSignature = state.configurationSignatureFor(data)
    state.label = String(data.label || "Editable section points")
    state.gridElement.setAttribute("aria-label", state.label)
    state.addButton.setAttribute("aria-label", `Add row to ${state.label}`)
  }

  state.build = data => {
    state.nextId = 1
    state.configure(data)
    state.selectedIds = Array.isArray(data.selected_ids)
      ? data.selected_ids.map(String)
      : []
    state.pasteAnchorRow = 0
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
      movableRows: state.movableRows,
    })
    state.table = table

    table.on("tableBuilt", () => {
      if (state.table !== table) return
      state.tableReady = true
      state.refreshDeleteLabels()
      state.applySelection(state.selectedIds)
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
    table.on("rowMoved", () => {
      state.renumber()
      state.emit()
    })
    table.on("clipboardPasted", () => {
      state.renumber()
      state.emit()
    })
  }

  state.updateConfiguration = data => {
    if (!state.table) return
    // Capture the browser's live rows before applying new catalogue choices.
    // The Python ``data.rows`` mirror can be one interaction behind, so using it
    // here would overwrite geometry and assignments during a catalogue rerun.
    const rows = state.currentRows()
    state.configure(data)
    state.applyIds(rows)
    const table = state.table
    table.setColumns(state.buildColumns())
    Promise.resolve(table.replaceData(rows)).then(() => {
      if (state.table !== table) return
      state.renumber()
      state.emit()
      state.redrawIfVisible(true)
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

  if (
    state.configurationSignatureFor(nextData)
    !== state.configurationSignature
  ) {
    state.updateConfiguration(nextData)
    state.applySelection(nextData.selected_ids)
    return state.cleanup
  }

  state.label = String(nextData.label || state.label)
  state.gridElement.setAttribute("aria-label", state.label)
  state.addButton.setAttribute("aria-label", `Add row to ${state.label}`)
  const requestedNext = Number(nextData.id_next)
  if (Number.isFinite(requestedNext) && requestedNext > state.nextId) {
    state.nextId = Math.floor(requestedNext)
  }
  state.refreshDeleteLabels()
  state.applySelection(nextData.selected_ids)
  state.redrawIfVisible(true)
  return state.cleanup
}

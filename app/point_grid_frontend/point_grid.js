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
    columns: [],
    idStart: 1,
    dataVersion: null,
    label: "Editable section points",
    pasteAnchorRow: 0,
    setStateValue: null,
  }

  state.isComplete = row => state.columns.every(column => {
    const value = row[column]
    if (value === null || value === undefined || value === "") return false
    return Number.isFinite(Number(value))
  })

  state.applyIds = rows => {
    let nextId = state.idStart
    rows.forEach(row => {
      row._id = state.isComplete(row) ? String(nextId++) : ""
    })
  }

  state.currentRows = () => {
    if (!state.table) return []
    return state.table.getData().map(row => {
      const output = {}
      state.columns.forEach(column => {
        const value = row[column]
        const number = Number(value)
        output[column] = (
          value === "" || value === null || value === undefined
          || !Number.isFinite(number)
        ) ? null : number
      })
      return output
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

  state.pasteToEditableColumns = text => state.splitPasteLines(text).map(line => {
    const cells = line.split("\t")
    const row = {}
    state.columns.forEach((column, index) => {
      const raw = cells[index] === undefined ? "" : String(cells[index]).trim()
      const number = Number(raw)
      row[column] = raw === "" || !Number.isFinite(number) ? null : number
    })
    return row
  })

  state.applyPaste = text => {
    if (!state.table) return
    const lines = state.splitPasteLines(text)
    if (!lines.length) return
    const pastedColumnCount = Math.max(...lines.map(line => line.split("\t").length))
    if (pastedColumnCount !== state.columns.length) {
      state.setWarning(
        `Pasted block has ${pastedColumnCount} column(s); this table expects `
        + `${state.columns.length} (${state.columns.join(", ")}). Nothing pasted.`,
      )
      return
    }

    state.clearWarning()
    const pastedRows = state.pasteToEditableColumns(text)
    const mergedRows = state.currentRows()
    const start = Math.min(state.pasteAnchorRow, mergedRows.length)
    pastedRows.forEach((row, index) => {
      mergedRows[start + index] = row
    })
    state.table.setData(mergedRows).then(() => {
      state.renumber()
      state.emit()
    })
  }

  state.buildColumns = () => {
    const definitions = [{
      title: "ID",
      field: "_id",
      width: 52,
      hozAlign: "right",
      headerSort: false,
      editable: false,
      clipboard: false,
      cssClass: "pg-id",
    }]

    state.columns.forEach(column => {
      definitions.push({
        title: column,
        field: column,
        editor: "number",
        editorParams: { selectContents: true },
        headerSort: false,
        hozAlign: "right",
        formatter: state.formatNumber,
        mutatorEdit: value => {
          if (value === "" || value === null || value === undefined) return null
          const number = Number(value)
          return Number.isFinite(number) ? number : null
        },
      })
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
    const requestedStart = Number(data.id_start)
    state.idStart = Number.isFinite(requestedStart) ? requestedStart : 1
    state.dataVersion = String(data.data_version ?? "0")
    state.label = String(data.label || "Editable section points")
    state.pasteAnchorRow = 0
    state.gridElement.setAttribute("aria-label", state.label)
    state.addButton.setAttribute("aria-label", `Add row to ${state.label}`)

    const rows = Array.isArray(data.rows)
      ? data.rows.map(row => ({ ...row }))
      : []
    state.applyIds(rows)

    if (state.table) {
      state.table.destroy()
      state.table = null
    }
    state.gridElement.replaceChildren()

    if (typeof globalThis.Tabulator !== "function") {
      state.setWarning("The point table could not be loaded. Reload Sector and try again.")
      return
    }

    state.table = new globalThis.Tabulator(state.gridElement, {
      data: rows,
      layout: "fitColumns",
      columns: state.buildColumns(),
      height: false,
      clipboard: true,
      clipboardPasteAction: "replace",
      clipboardPasteParser: state.pasteToEditableColumns,
      addRowPos: "bottom",
      reactiveData: false,
    })

    state.table.on("tableBuilt", () => state.refreshDeleteLabels())
    state.table.on("renderComplete", () => state.refreshDeleteLabels())
    state.table.on("cellEditing", cell => {
      const position = cell.getRow().getPosition(true)
      state.pasteAnchorRow = position > 0 ? position - 1 : 0
    })
    state.table.on("cellEdited", () => {
      state.clearWarning()
      state.renumber()
      state.emit()
    })
    state.table.on("rowDeleted", () => {
      state.renumber()
      state.emit()
    })
    state.table.on("clipboardPasted", () => {
      state.renumber()
      state.emit()
    })
  }

  addButton.addEventListener("click", () => {
    if (!state.table) return
    state.table.addRow({}).then(() => {
      state.renumber()
      state.emit()
    })
  })

  wrap.addEventListener("paste", event => {
    if (!state.table) return
    const clipboard = event.clipboardData
    const text = clipboard ? clipboard.getData("text") : ""
    const isBlock = text.includes("\t") || /\n/.test(text.trim())
    if (!text || !isBlock) return
    event.preventDefault()
    event.stopPropagation()
    state.applyPaste(text)
  }, { capture: true })

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
    return
  }

  state.label = String(nextData.label || state.label)
  state.gridElement.setAttribute("aria-label", state.label)
  state.addButton.setAttribute("aria-label", `Add row to ${state.label}`)
  state.refreshDeleteLabels()
}

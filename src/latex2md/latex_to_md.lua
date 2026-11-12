-- Pandoc Lua filter used for LaTeX -> Markdown. It keeps the output to plain,
-- portable Markdown (CommonMark/GFM + $math$) rather than pandoc dialect.

local stringify = pandoc.utils.stringify

-- Lists: tight when every item is a single paragraph.
local function tighten(list)
  for _, item in ipairs(list.content) do
    if #item ~= 1 or item[1].t ~= "Para" then
      return nil
    end
  end
  for i, item in ipairs(list.content) do
    list.content[i] = { pandoc.Plain(item[1].content) }
  end
  return list
end

function BulletList(list) return tighten(list) end
function OrderedList(list) return tighten(list) end

-- Code: class-less blocks get "text" so they are fenced, not indented.
function CodeBlock(block)
  if #block.classes == 0 then
    block.classes = { "text" }
  end
  return block
end

-- LaTeX ~ and "\ " become invisible non-breaking spaces, which break
-- copy/paste of code and text search. Use ordinary spaces.
local NBSP = "\u{00A0}"

function Code(code)
  code.text = code.text:gsub(NBSP, " ")
  return code
end

function Str(str)
  if not str.text:find(NBSP, 1, true) then
    return nil
  end
  local inlines = pandoc.List()
  local start = 1
  while true do
    local from, to = str.text:find(NBSP, start, true)
    if not from then
      break
    end
    if from > start then
      inlines:insert(pandoc.Str(str.text:sub(start, from - 1)))
    end
    inlines:insert(pandoc.Space())
    start = to + 1
  end
  if start <= #str.text then
    inlines:insert(pandoc.Str(str.text:sub(start)))
  end
  return inlines
end

-- Math: \label/\nonumber are LaTeX-only and make KaTeX/MathJax fail.
function Math(math)
  math.text = math.text:gsub("%s*\\label%s*%b{}", ""):gsub("%s*\\nonumber", ""):gsub("%s*\\notag", "")
  return math
end

-- Display math gets its own paragraph instead of sitting inside one.
function Para(para)
  local blocks, current = {}, {}
  local function flush()
    while #current > 0 and (current[#current].t == "Space" or current[#current].t == "SoftBreak") do
      table.remove(current)
    end
    while #current > 0 and (current[1].t == "Space" or current[1].t == "SoftBreak") do
      table.remove(current, 1)
    end
    if #current > 0 then
      table.insert(blocks, pandoc.Para(current))
    end
    current = {}
  end
  local split = false
  for _, inline in ipairs(para.content) do
    if inline.t == "Math" and inline.mathtype == "DisplayMath" then
      flush()
      table.insert(blocks, pandoc.Para({ inline }))
      split = true
    else
      table.insert(current, inline)
    end
  end
  if not split then
    return nil
  end
  flush()
  return blocks
end

-- Cross-references: the anchors do not exist in Markdown, so keep the text.
-- Unresolved ones ("[eq:loss]") become "(eq:loss)".
function Link(link)
  if link.target:sub(1, 1) ~= "#" then
    return nil
  end
  local text = stringify(link.content)
  local label = text:match("^%[(.*)%]$")
  if label then
    return pandoc.Str("(" .. label .. ")")
  end
  return link.content
end

-- Divs (table/figure wrappers, environments) are unwrapped.
function Div(div)
  return div.content
end

-- Figures: a single image whose alt text is the caption.
local function first_image(blocks)
  local found
  pandoc.walk_block(pandoc.Div(blocks), {
    Image = function(image)
      found = found or image
    end,
  })
  return found
end

if pandoc.Figure then
  function Figure(figure)
    local image = first_image(figure.content)
    if not image then
      return figure.content
    end
    local caption = pandoc.utils.blocks_to_inlines(figure.caption.long or {})
    if #caption > 0 then
      image.caption = caption
    end
    return pandoc.Para({ image })
  end
end

-- Table captions use pandoc-only syntax (": caption"); emit a paragraph.
function Table(tbl)
  local caption = pandoc.utils.blocks_to_inlines(tbl.caption.long or {})
  if #caption == 0 then
    return nil
  end
  tbl.caption.long = {}
  local label = pandoc.List({ pandoc.Strong({ pandoc.Str("Table:") }), pandoc.Space() })
  return { pandoc.Para(label .. caption), tbl }
end

-- Title/author/abstract live in metadata. With front matter disabled, move
-- the abstract into the body so it is not lost.
function Pandoc(doc)
  if doc.meta.latex2md_body_abstract and doc.meta.abstract then
    local abstract = doc.meta.abstract
    local blocks = pandoc.utils.type(abstract) == "Inlines" and { pandoc.Para(abstract) } or abstract
    local body = pandoc.List({ pandoc.Header(1, { pandoc.Str("Abstract") }) })
    body:extend(blocks)
    body:extend(doc.blocks)
    doc.blocks = body
  end
  doc.meta.latex2md_body_abstract = nil
  return doc
end

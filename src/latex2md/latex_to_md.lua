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

-- Cross-references are resolved to text before pandoc runs (structure.py).
-- pandoc's own reference links point at anchors Markdown does not have, so
-- keep their text; unresolved ones ("[eq:loss]") become "(eq:loss)".
-- Explicit \\href{#label}{...} links (anchors=True) are resolved in Pandoc().
function Link(link)
  if link.target:sub(1, 1) ~= "#" then
    return nil
  end
  if not link.attributes["reference-type"] then
    return nil
  end
  local text = stringify(link.content)
  local label = text:match("^%[(.*)%]$")
  if label then
    return pandoc.Str("(" .. label .. ")")
  end
  return link.content
end

-- Spans (from \\label in running text, \\textsc-less styling, ...) would be
-- written as raw HTML; keep only their content.
function Span(span)
  return span.content
end

-- Divs (table/figure wrappers, environments) are unwrapped.
function Div(div)
  return div.content
end

-- Numbered captions arrive as "Figure 2: ..." / "Table 1: ..." (prefixed in
-- structure.py, which knows LaTeX's numbering); split off that label.
local function split_label(inlines, word)
  if #inlines >= 3 and inlines[1].t == "Str" and inlines[1].text == word and inlines[2].t == "Space"
      and inlines[3].t == "Str" and inlines[3].text:match("^[%w.]+:$") then
    local rest = pandoc.List()
    for i = 5, #inlines do
      rest:insert(inlines[i])
    end
    return pandoc.List({ inlines[1], inlines[2], inlines[3] }), rest
  end
  return nil, inlines
end

local function caption_para(caption, word)
  local label, rest = split_label(caption, word)
  if not label then
    return pandoc.Para(caption)
  end
  return pandoc.Para(pandoc.List({ pandoc.Strong(label), pandoc.Space() }) .. rest)
end

-- Figures: a single image whose alt text is the caption. Figures with several
-- images (subfigures) keep each image, then the caption as a paragraph.
local function images_in(blocks)
  local found = {}
  pandoc.walk_block(pandoc.Div(blocks), {
    Image = function(image)
      table.insert(found, image)
    end,
  })
  return found
end

if pandoc.Figure then
  function Figure(figure)
    local images = images_in(figure.content)
    local caption = pandoc.utils.blocks_to_inlines(figure.caption.long or {})
    if #images == 1 then
      if #caption > 0 then
        images[1].caption = caption
      end
      return pandoc.Para({ images[1] })
    end
    local blocks = pandoc.List(figure.content)
    if #caption > 0 then
      blocks:insert(caption_para(caption, "Figure"))
    end
    return blocks
  end
end

-- Table captions use pandoc-only syntax (": caption"); emit a paragraph.
function Table(tbl)
  local caption = pandoc.utils.blocks_to_inlines(tbl.caption.long or {})
  if #caption == 0 then
    return nil
  end
  tbl.caption.long = {}
  local label = split_label(caption, "Table")
  if label then
    return { caption_para(caption, "Table"), tbl }
  end
  local prefix = pandoc.List({ pandoc.Strong({ pandoc.Str("Table:") }), pandoc.Space() })
  return { pandoc.Para(prefix .. caption), tbl }
end

-- GitHub-style heading ids, which GitHub, GitLab and most Markdown renderers
-- generate on their own: lower case, punctuation dropped, spaces to "-",
-- "-1", "-2"... for repeats. Plain Markdown has no other anchor syntax.
local function heading_slugs(blocks)
  local slugs, seen = {}, {}
  for _, block in ipairs(blocks) do
    if block.t == "Header" then
      local slug = pandoc.text.lower(stringify(block.content))
      slug = slug:gsub("[%p]", function(c)
        return (c == "-" or c == "_") and c or ""
      end):gsub(" ", "-")
      local count = seen[slug]
      seen[slug] = (count or 0) + 1
      if count then
        slug = slug .. "-" .. count
      end
      if block.identifier ~= "" then
        slugs[block.identifier] = slug
      end
    end
  end
  return slugs
end

local function resolve_anchors(doc, enabled)
  local slugs = enabled and heading_slugs(doc.blocks) or {}
  return doc:walk({
    Link = function(link)
      if link.target:sub(1, 1) ~= "#" then
        return nil
      end
      local slug = slugs[link.target:sub(2)]
      if slug then
        link.target = "#" .. slug
        return link
      end
      return link.content
    end,
  })
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
  local anchors = doc.meta.latex2md_anchors and true or false
  doc.meta.latex2md_body_abstract = nil
  doc.meta.latex2md_anchors = nil
  return resolve_anchors(doc, anchors)
end

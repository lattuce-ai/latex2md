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

-- citeproc's reference list (Div#refs of csl-entry Divs) becomes a
-- "References" heading and a bullet list, like thebibliography. It is
-- tagged here and moved to the \\bibliography position in Pandoc().
local function references_block(div)
  local items = {}
  for _, entry in ipairs(div.content) do
    local blocks = entry.t == "Div" and entry.content or { entry }
    table.insert(items, { pandoc.Plain(pandoc.utils.blocks_to_inlines(blocks)) })
  end
  local blocks = { pandoc.Header(1, { pandoc.Str("References") }) }
  if #items > 0 then
    table.insert(blocks, pandoc.BulletList(items))
  end
  return pandoc.Div(blocks, pandoc.Attr("latex2md-references"))
end

-- Divs (table/figure wrappers, environments) are unwrapped.
function Div(div)
  if div.identifier == "refs" then
    return references_block(div)
  end
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

-- With --citeproc, pandoc >= 3.2 writes rendered citations even when the
-- citations extension is on. To keep [@key] on every version, write each
-- citation with a citeproc-free writer and emit it as raw Markdown.
local function citations_as_markdown(cite)
  local doc = pandoc.Pandoc({ pandoc.Plain({ pandoc.Cite({}, cite.citations) }) })
  local text = pandoc.write(doc, "markdown", pandoc.WriterOptions({ wrap_text = "wrap-none" }))
  return pandoc.RawInline("markdown", (text:gsub("%s+$", "")))
end

local function place_references(doc)
  local references, position
  local blocks = pandoc.List()
  for _, block in ipairs(doc.blocks) do
    if block.t == "Div" and block.identifier == "latex2md-references" then
      references = block.content
    elseif block.t == "Para" and #block.content == 1 and block.content[1].t == "Str"
        and block.content[1].text == "LATEX2MDREFERENCES" then
      position = position or #blocks + 1
    else
      blocks:insert(block)
    end
  end
  if references then
    for i, block in ipairs(references) do
      blocks:insert((position or #blocks + 1) + i - 1, block)
    end
  end
  doc.blocks = blocks
  return doc
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
  local citeproc = doc.meta.latex2md_citeproc and true or false
  local rendered = doc.meta.latex2md_cite_rendered and true or false
  for _, key in ipairs({ "latex2md_body_abstract", "latex2md_anchors", "latex2md_citeproc", "latex2md_cite_rendered" }) do
    doc.meta[key] = nil
  end
  if citeproc then
    -- These point at latex2md's temporary copies.
    doc.meta.bibliography = nil
    doc.meta.csl = nil
    doc = doc:walk({
      Cite = function(cite)
        if rendered then
          return cite.content
        end
        return citations_as_markdown(cite)
      end,
    })
  end
  return resolve_anchors(place_references(doc), anchors)
end

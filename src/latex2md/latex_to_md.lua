-- Pandoc Lua filter used for LaTeX -> Markdown.
-- * Makes lists tight when every item is a single paragraph.
-- * Gives class-less code blocks a "text" class so they are written as
--   fenced blocks instead of indented ones.

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

function CodeBlock(block)
  if #block.classes == 0 then
    block.classes = { "text" }
  end
  return block
end

-- \texttt{a\ b} and \texttt{a~b} come through as non-breaking spaces; in
-- Markdown inline code that breaks copy/paste, so use plain spaces.
function Code(code)
  code.text = code.text:gsub("\u{00A0}", " ")
  return code
end

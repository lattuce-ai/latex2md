# Introduction

We prove Theorem 2.1 using Lemma 2.2, see Section 2 and Sections 1 and 2. Equation (1) and (3) hold; so does equation (1). Figure 1 has (a) and Figure 1b; Table 1 lists results. Missing: (nope).

$$E = mc^2 \tag{1}$$

An unnumbered one:

$$a = b$$

$$\begin{aligned}
f(x) &= x^2 \\
  g(x) &= x^3 \\
  h(x) &= x^4
\end{aligned} \tag{2–3}$$

$$\begin{aligned}
p &= q
\end{aligned}$$

$$\begin{gathered}
u = v \\
  w = z
\end{gathered} \tag{$\star$}$$

$$\begin{alignedat}{2}
a &= b &\quad c &= d
\end{alignedat} \tag{4}$$

# Method

## Setup

**Definition 1 (Sparse map).** A map $f\colon \mathbb{R}^n \to \mathbb{R}^m$ is *sparse* if it has few non-zeros.

**Theorem 2.1 (Main result).** Every sparse map is fast.

**Lemma 2.2.** Lemmas share the theorem counter (Equation (2)).

**Remark.** Remarks are not numbered.

*Proof.* Apply Lemma 2.2 twice. ∎

![(a) Left panel.](left.png)

![(b) Right panel.](right.png)

**Figure 1:** Two panels.

**Table 1:** Results.

| Model | Score |
|:------|------:|
| A     |     1 |

**Algorithm 1:** Gradient descent with clipping

```text
    Require: step size $\eta > 0$
 1: function Train($D$)
 2:     $w \gets 0$ ▷ start at zero
 3:     for $t = 1, \dots, T$ do
 4:         if $\|g_t\| > \tau$ then
 5:             $g_t \gets \tau g_t / \|g_t\|$
 6:         else
 7:             Log($t$)
 8:         end if
 9:         $w \gets w - \eta g_t$
10:     end for
11:     return $w$
12: end function
```

Algorithm 1 loops in line 3.

1. First
2. Second

Item 2 matters.

Content of an unknown environment is kept.

# Proofs

See Appendix A and Definition 1.

package org.epiprot.phone.model

import kotlin.math.abs
import kotlin.math.exp

/**
 * Evaluates a LightGBM model on the phone, read from LightGBM's own text format
 * (`booster.model_to_string()`), so no native library is needed.
 *
 * Supports what the EpiProt models use: binary objective, numerical splits, missing values
 * (NaN / zero / none, default direction), single-leaf trees. Categorical splits are rejected.
 * Decisions follow LightGBM's `NumericalDecision` exactly.
 */
class Gbdt private constructor(
    private val trees: List<Tree>,
    val numFeatures: Int,
    private val sigmoid: Double,
) {
    private class Tree(
        val feature: IntArray,
        val threshold: DoubleArray,
        val decision: IntArray,
        val left: IntArray,
        val right: IntArray,
        val leaf: DoubleArray,
    ) {
        fun value(x: DoubleArray): Double {
            if (feature.isEmpty()) return leaf[0]
            var node = 0
            while (node >= 0) {
                var v = x[feature[node]]
                val d = decision[node]
                val missing = (d shr 2) and 3
                if (v.isNaN() && missing != MISSING_NAN) v = 0.0
                node = if ((missing == MISSING_ZERO && abs(v) <= ZERO) || (missing == MISSING_NAN && v.isNaN())) {
                    if (d and DEFAULT_LEFT != 0) left[node] else right[node]
                } else if (v <= threshold[node]) left[node] else right[node]
            }
            return leaf[node.inv()]
        }
    }

    fun rawScore(x: DoubleArray): Double {
        require(x.size == numFeatures) { "expected $numFeatures features, got ${x.size}" }
        var s = 0.0
        for (t in trees) s += t.value(x)
        return s
    }

    /** Seizure probability as LightGBM's `predict()` returns it. */
    fun predict(x: DoubleArray): Double = 1.0 / (1.0 + exp(-sigmoid * rawScore(x)))

    val numTrees: Int get() = trees.size

    companion object {
        private const val DEFAULT_LEFT = 2
        private const val CATEGORICAL = 1
        private const val MISSING_ZERO = 1
        private const val MISSING_NAN = 2
        private const val ZERO = 1e-35

        /** LightGBM writes infinities as "inf" / "-inf". */
        private fun num(s: String): Double = when (s.lowercase()) {
            "inf", "+inf", "infinity" -> Double.POSITIVE_INFINITY
            "-inf", "-infinity" -> Double.NEGATIVE_INFINITY
            "nan", "-nan" -> Double.NaN
            else -> s.toDouble()
        }

        fun parse(text: String): Gbdt {
            val lines = text.lineSequence().iterator()
            var maxFeature = -1
            var sigmoid = 1.0
            val trees = ArrayList<Tree>()
            var cur: MutableMap<String, String>? = null

            fun finishTree() {
                val m = cur ?: return
                val leaves = m.getValue("num_leaves").toInt()
                fun ints(k: String) = if (leaves > 1) m.getValue(k).split(' ').map { it.toInt() }.toIntArray() else IntArray(0)
                fun dbls(k: String) = m.getValue(k).split(' ').map { num(it) }.toDoubleArray()
                val decision = ints("decision_type")
                require(decision.none { it and CATEGORICAL != 0 }) { "categorical splits are not supported" }
                trees += Tree(
                    feature = ints("split_feature"),
                    threshold = if (leaves > 1) dbls("threshold") else DoubleArray(0),
                    decision = decision,
                    left = ints("left_child"),
                    right = ints("right_child"),
                    leaf = dbls("leaf_value"),
                )
                cur = null
            }

            while (lines.hasNext()) {
                val line = lines.next().trim()
                when {
                    line.startsWith("Tree=") -> { finishTree(); cur = HashMap() }
                    line == "end of trees" -> { finishTree(); break }
                    line.startsWith("max_feature_idx=") -> maxFeature = line.substringAfter('=').toInt()
                    line.startsWith("objective=") -> {
                        val obj = line.substringAfter('=')
                        require(obj.startsWith("binary")) { "only binary models are supported: $obj" }
                        Regex("sigmoid:([0-9.eE+-]+)").find(obj)?.let { sigmoid = it.groupValues[1].toDouble() }
                    }
                    cur != null && '=' in line -> cur!![line.substringBefore('=')] = line.substringAfter('=')
                }
            }
            require(trees.isNotEmpty() && maxFeature >= 0) { "not a LightGBM text model" }
            return Gbdt(trees, maxFeature + 1, sigmoid)
        }
    }
}

from datetime import datetime
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from datetime import date

from .graficos import escala, intervalos_do_grafico, montar_grafico
from .models import InstagramConnection, SeguidoresDia
from .views import _motivo_erro_insights, _resolver_periodo, _sincronizar_seguidores, _somar_seguidores


def _local(*args):
    return timezone.make_aware(datetime(*args))


def _congelar_em(*args):
    return mock.patch('core.views.timezone.now', return_value=_local(*args))


def _fmt(momento):
    return timezone.localtime(momento).strftime('%d/%m/%Y %H:%M')


class ResolverPeriodoTests(SimpleTestCase):
    def test_hoje_compara_com_ontem_inteiro(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('hoje', None, None)
        self.assertEqual(_fmt(p.desde), '24/09/2026 00:00')
        self.assertEqual(_fmt(p.ate), '24/09/2026 11:25')
        self.assertEqual(_fmt(p.anterior_desde), '23/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '23/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. ontem')

    def test_semana_compara_ate_o_mesmo_dia_da_semana_passada(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('semana', None, None)
        self.assertEqual(_fmt(p.desde), '21/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_desde), '14/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '17/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. semana passada até qui')

    def test_mes_compara_ate_o_mesmo_dia_do_mes_passado(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.desde), '01/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_desde), '01/08/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '24/08/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. mês passado até 24/08')

    def test_mes_no_dia_31_usa_o_ultimo_dia_do_mes_anterior(self):
        with _congelar_em(2026, 3, 31, 9, 0):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.anterior_ate), '28/02/2026 23:59')

    def test_mes_em_janeiro_compara_com_dezembro_do_ano_anterior(self):
        with _congelar_em(2026, 1, 10, 8, 0):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.anterior_desde), '01/12/2025 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '10/12/2025 23:59')

    def test_mes_passado_nao_existe_mais_e_volta_para_hoje(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('mes_passado', None, None)
        self.assertEqual(p.chave, 'hoje')

    def test_periodo_compara_com_os_mesmos_dias_anteriores(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', '2026-09-20', '2026-09-24')
        self.assertEqual(_fmt(p.ate), '24/09/2026 11:25')
        self.assertEqual(_fmt(p.anterior_desde), '15/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '19/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. 5 dias anteriores')

    def test_periodo_com_datas_invertidas_e_corrigido(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', '2026-08-15', '2026-08-01')
        self.assertEqual(p.label, '01/08/2026 – 15/08/2026')

    def test_periodo_invalido_volta_para_hoje(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', 'xx', 'yy')
        self.assertEqual(p.chave, 'hoje')


def _resposta_erro(status, corpo):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = corpo
    return resp


class MotivoErroInsightsTests(SimpleTestCase):
    def test_post_anterior_a_conta_profissional(self):
        resp = _resposta_erro(400, {'error': {'code': 100, 'error_subcode': 2108006, 'message': 'Media Posted Before Business Account Conversion'}})
        self.assertIn('antes da conta virar profissional', _motivo_erro_insights(resp))

    def test_permissao_nao_concedida(self):
        resp = _resposta_erro(403, {'error': {'code': 10, 'message': 'Application does not have permission for this action'}})
        self.assertIn('permissão de estatísticas', _motivo_erro_insights(resp))

    def test_token_expirado(self):
        resp = _resposta_erro(401, {'error': {'code': 190, 'message': 'Error validating access token'}})
        self.assertIn('expirou', _motivo_erro_insights(resp))

    def test_erro_desconhecido_mostra_mensagem_do_instagram(self):
        resp = _resposta_erro(400, {'error': {'code': 100, 'message': '(#100) The metric views is not supported'}})
        self.assertIn('The metric views is not supported', _motivo_erro_insights(resp))

    def test_resposta_sem_json(self):
        resp = mock.Mock(status_code=502)
        resp.json.side_effect = ValueError
        self.assertIn('HTTP 502', _motivo_erro_insights(resp))


class IntervalosDoGraficoTests(SimpleTestCase):
    hoje = date(2026, 9, 24)

    def test_hoje_mostra_os_ultimos_7_dias(self):
        subtitulo, intervalos = intervalos_do_grafico('hoje', self.hoje, self.hoje, self.hoje)
        self.assertEqual(subtitulo, 'Últimos 7 dias')
        self.assertEqual([i.rotulo for i in intervalos], ['sex 18', 'sáb 19', 'dom 20', 'seg 21', 'ter 22', 'qua 23', 'qui 24'])

    def test_semana_mostra_8_semanas_comecando_na_segunda(self):
        _, intervalos = intervalos_do_grafico('semana', self.hoje, self.hoje, self.hoje)
        self.assertEqual(len(intervalos), 8)
        self.assertEqual((intervalos[0].inicio, intervalos[0].fim), (date(2026, 8, 3), date(2026, 8, 9)))
        self.assertEqual((intervalos[-1].inicio, intervalos[-1].fim), (date(2026, 9, 21), self.hoje))

    def test_mes_mostra_os_meses_do_ano_ate_hoje(self):
        subtitulo, intervalos = intervalos_do_grafico('mes', self.hoje, self.hoje, self.hoje)
        self.assertEqual(subtitulo, 'Meses de 2026')
        self.assertEqual([i.rotulo for i in intervalos], ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set'])
        self.assertEqual(intervalos[1].fim, date(2026, 2, 28))
        self.assertEqual(intervalos[-1].fim, self.hoje)

    def test_periodo_curto_e_por_dia_e_longo_e_por_mes(self):
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2026, 9, 1), date(2026, 9, 10), self.hoje)
        self.assertEqual((subtitulo, len(intervalos)), ('Por dia', 10))
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2026, 7, 1), date(2026, 8, 31), self.hoje)
        self.assertEqual((subtitulo, len(intervalos)), ('Por semana', 9))
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2025, 11, 15), date(2026, 9, 30), self.hoje)
        self.assertEqual(subtitulo, 'Por mês')
        self.assertEqual(intervalos[0].rotulo, 'nov/25')
        self.assertEqual(intervalos[0].inicio, date(2025, 11, 15))
        self.assertEqual(intervalos[-1].fim, self.hoje)


class EscalaEGraficoTests(SimpleTestCase):
    def test_escala_usa_numeros_redondos(self):
        self.assertEqual(escala(0, 37), [0, 10, 20, 30, 40])
        self.assertEqual(escala(0, 2), [0, 1, 2])
        self.assertEqual(escala(-3, 12), [-5, 0, 5, 10, 15])
        self.assertEqual(escala(0, 0), [0, 1])

    def test_barras_negativas_crescem_para_baixo_a_partir_do_zero(self):
        _, intervalos = intervalos_do_grafico('hoje', date(2026, 9, 24), date(2026, 9, 24), date(2026, 9, 24))
        grafico = montar_grafico('x', intervalos, [10, -5, None, 0, 15, 3, 1])
        self.assertEqual(grafico['base'], 25.0)
        positiva, negativa, vazia = grafico['barras'][:3]
        self.assertEqual((positiva['inferior'], positiva['altura']), (25.0, 50.0))
        self.assertEqual((negativa['inferior'], negativa['altura']), (0.0, 25.0))
        self.assertTrue(negativa['negativo'])
        self.assertNotIn('altura', vazia)

    def test_sem_nenhum_dado_fica_vazio(self):
        _, intervalos = intervalos_do_grafico('hoje', date(2026, 9, 24), date(2026, 9, 24), date(2026, 9, 24))
        self.assertTrue(montar_grafico('x', intervalos, [None] * 7)['vazio'])


class SeguidoresTests(TestCase):
    def test_soma_marca_incompleto_quando_falta_dia_encerrado(self):
        por_dia = {date(2026, 9, 21): 3, date(2026, 9, 23): 2}
        self.assertEqual(_somar_seguidores(por_dia, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (5, False))
        por_dia[date(2026, 9, 22)] = 1
        self.assertEqual(_somar_seguidores(por_dia, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (6, True))
        self.assertEqual(_somar_seguidores({}, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (None, False))

    def test_sincronizar_grava_cada_dia_pelo_end_time(self):
        from django.contrib.auth.models import User
        usuario = User.objects.create(username='teste')
        conexao = InstagramConnection.objects.create(user=usuario, instagram_user_id='123', access_token='t')
        resposta = mock.Mock(ok=True)
        resposta.json.return_value = {'data': [{'values': [
            {'value': 4, 'end_time': '2026-09-22T07:00:00+0000'},
            {'value': -1, 'end_time': '2026-09-23T07:00:00+0000'},
        ]}]}
        with mock.patch('core.views.requests.get', return_value=resposta):
            _sincronizar_seguidores(conexao)
            resposta.json.return_value['data'][0]['values'][1]['value'] = 2
            _sincronizar_seguidores(conexao)
        dias = dict(SeguidoresDia.objects.values_list('data', 'novos_seguidores'))
        self.assertEqual(dias, {date(2026, 9, 21): 4, date(2026, 9, 22): 2})
